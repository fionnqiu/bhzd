import { useId, useMemo, useState, type FormEvent } from "react";

import { Button } from "../../components/Button";

type JsonScalar = string | number | boolean | null;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isJsonScalar = (value: unknown): value is JsonScalar =>
  value === null ||
  typeof value === "string" ||
  typeof value === "number" ||
  typeof value === "boolean";

export const createEmptyResponseShape = (template: unknown): unknown => {
  if (Array.isArray(template)) {
    return template.length === 0
      ? []
      : [createEmptyResponseShape(template[0])];
  }
  if (template === null) {
    return null;
  }
  if (typeof template === "string") {
    return "";
  }
  if (typeof template === "number") {
    return 0;
  }
  if (typeof template === "boolean") {
    return false;
  }
  if (isRecord(template)) {
    return Object.fromEntries(
      Object.entries(template).map(([key, nested]) => [
        key,
        createEmptyResponseShape(nested),
      ]),
    );
  }

  return null;
};

const explicitScalarOptions = (
  responseSpace: unknown,
  answerTemplate: unknown,
): JsonScalar[] | null => {
  if (!isJsonScalar(answerTemplate) || !isRecord(responseSpace)) {
    return null;
  }

  const type = responseSpace.type;
  if (
    type !== "finite_scalar" &&
    type !== "finite_closed_scalar" &&
    type !== "finite_scalar_set"
  ) {
    return null;
  }

  const declaredValues =
    responseSpace.values ??
    responseSpace.allowed_values ??
    responseSpace.options;
  if (
    !Array.isArray(declaredValues) ||
    declaredValues.length === 0 ||
    !declaredValues.every(isJsonScalar)
  ) {
    return null;
  }

  return declaredValues;
};

interface StructuredResponseEditorProps {
  answerTemplate: unknown;
  responseSpace?: unknown;
  onSubmit(submission: unknown): void;
  onEdit?(): void;
}

export function StructuredResponseEditor({
  answerTemplate,
  responseSpace,
  onSubmit,
  onEdit,
}: StructuredResponseEditorProps) {
  const editorId = useId();
  const initialValue = useMemo(
    () => JSON.stringify(createEmptyResponseShape(answerTemplate), null, 2),
    [answerTemplate],
  );
  const options = useMemo(
    () => explicitScalarOptions(responseSpace, answerTemplate),
    [answerTemplate, responseSpace],
  );
  const [jsonValue, setJsonValue] = useState(initialValue);
  const [selectedOption, setSelectedOption] = useState("");
  const [syntaxError, setSyntaxError] = useState<string | null>(null);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    let submission: unknown;
    try {
      if (options === null) {
        submission = JSON.parse(jsonValue);
      } else {
        if (selectedOption === "") {
          setSyntaxError("请选择一个声明的答案值后再提交自检。");
          return;
        }
        submission = options[Number(selectedOption)];
      }
    } catch {
      setSyntaxError("答案 JSON 存在语法错误，请修正后再次提交自检。");
      return;
    }

    setSyntaxError(null);
    onSubmit(submission);
  };

  const loadStandardExample = () => {
    setSyntaxError(null);
    onEdit?.();

    if (options === null) {
      setJsonValue(JSON.stringify(answerTemplate, null, 2));
      return;
    }

    const standardOptionIndex = options.findIndex((option) =>
      Object.is(option, answerTemplate),
    );
    setSelectedOption(
      standardOptionIndex === -1 ? "" : String(standardOptionIndex),
    );
  };

  return (
    <form className="response-editor" onSubmit={handleSubmit}>
      {options === null ? (
        <label className="response-editor__field" htmlFor={editorId}>
          <span>结构化答案</span>
          <textarea
            id={editorId}
            value={jsonValue}
            rows={12}
            spellCheck={false}
            autoComplete="off"
            onChange={(event) => {
              setJsonValue(event.target.value);
              setSyntaxError(null);
              onEdit?.();
            }}
          />
        </label>
      ) : (
        <label className="response-editor__field" htmlFor={editorId}>
          <span>答案选择</span>
          <select
            id={editorId}
            value={selectedOption}
            onChange={(event) => {
              setSelectedOption(event.target.value);
              setSyntaxError(null);
              onEdit?.();
            }}
          >
            <option value="">请选择</option>
            {options.map((option, index) => (
              <option key={`${typeof option}-${String(option)}`} value={index}>
                {JSON.stringify(option)}
              </option>
            ))}
          </select>
        </label>
      )}

      {syntaxError !== null ? (
        <p className="response-editor__error" role="alert">
          {syntaxError}
        </p>
      ) : null}

      <div className="response-editor__actions">
        <p>答案只在本地确定性评估器中核对。</p>
        {import.meta.env.MODE === "test" ? (
          <Button variant="quiet" type="button" onClick={loadStandardExample}>
            载入标准结构示例
          </Button>
        ) : null}
        <Button variant="primary" type="submit">
          提交自检
        </Button>
      </div>
    </form>
  );
}
