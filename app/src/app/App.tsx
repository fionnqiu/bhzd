import { RouterProvider } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import { ScenarioProvider } from "./ScenarioContext";
import { ToastProvider } from "../components";
import router from "./router";

/**
 * 应用根组件。
 * Provider 顺序：Toast（无依赖）→ Auth（401 回调清用户态触发守卫重定向）
 * → Scenario（仅学生壳消费，但放根级避免布局间切换时重建选择）。
 */
export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <ScenarioProvider>
          <RouterProvider router={router} />
        </ScenarioProvider>
      </AuthProvider>
    </ToastProvider>
  );
}
