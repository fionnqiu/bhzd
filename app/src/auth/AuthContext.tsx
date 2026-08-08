/**
 * 认证上下文（蓝图 §6.1 + routers/auth.py）。
 *
 * 关键行为（为什么）：
 * - 挂载时引导一次 GET /api/auth/session：既恢复登录态，又拿到本轮 CSRF
 *   令牌（后端每次调用都轮换令牌，见 auth.py session_info）。引导完成前
 *   `bootstrapping=true`，路由守卫据此先渲染加载态而不是误判未登录。
 * - 注册 setOnUnauthorized：业务请求遇到 401（会话过期/被吊销）时清掉
 *   用户态，交由路由守卫把用户送回 /login——客户端不直接操作路由，避免
 *   AuthProvider 与 Router 的层级耦合。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  ApiRequestError,
  api,
  setCsrfToken,
  setOnUnauthorized,
} from "../api/client";
import type {
  MessageResponse,
  RegisterResponse,
  Role,
  SessionResponse,
  User,
} from "../api/types";
import { createPasswordEnvelope } from "./passwordCrypto";

export interface AuthContextValue {
  user: User | null;
  csrfToken: string | null;
  /** 首次会话引导进行中（守卫应等待而非重定向） */
  bootstrapping: boolean;
  login: (email: string, password: string) => Promise<SessionResponse>;
  logout: () => Promise<void>;
  register: (input: RegisterInput) => Promise<RegisterResponse>;
  /** 重新拉取会话（轮换 CSRF 并刷新用户信息，如邮箱验证完成后） */
  refreshSession: () => Promise<void>;
  hasRole: (...roles: Role[]) => boolean;
}

export interface RegisterInput {
  email: string;
  name: string;
  password: string;
  role?: "student" | "teacher";
  teacher_invite?: string;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);

  const applySession = useCallback((data: SessionResponse) => {
    setUser(data.user);
    setToken(data.csrf_token);
    setCsrfToken(data.csrf_token);
  }, []);

  const clearSession = useCallback(() => {
    setUser(null);
    setToken(null);
    setCsrfToken(null);
  }, []);

  const refreshSession = useCallback(async () => {
    const data = await api.get<SessionResponse>("/api/auth/session");
    applySession(data);
  }, [applySession]);

  useEffect(() => {
    // 会话失效回调：清本地态即可，跳转交给路由守卫（见模块注释）
    setOnUnauthorized(() => clearSession());
    return () => setOnUnauthorized(null);
  }, [clearSession]);

  useEffect(() => {
    // 只在挂载时引导一次；未登录的 401 是正常路径（静默转未登录态）
    const controller = new AbortController();
    (async () => {
      try {
        const data = await api.get<SessionResponse>("/api/auth/session", undefined, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) applySession(data);
      } catch (err) {
        if (controller.signal.aborted) return;
        if (!(err instanceof ApiRequestError && err.status === 401)) {
          // 网络错误等非 401：保持未登录态但不阻断应用（用户可重试登录）
          console.warn("会话引导失败", err);
        }
      } finally {
        if (!controller.signal.aborted) setBootstrapping(false);
      }
    })();
    return () => {
      // The bootstrap response must not update a provider that was already unmounted.
      controller.abort();
    };
  }, [applySession]);

  const login = useCallback(
    async (email: string, password: string) => {
      const passwordEnvelope = await createPasswordEnvelope(password);
      const data = await api.post<SessionResponse>("/api/auth/login", {
        email,
        passwordEnvelope,
      });
      applySession(data);
      return data;
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    try {
      await api.post<MessageResponse>("/api/auth/logout");
    } finally {
      // 服务端失败也清本地态：让用户一定能回到未登录（auth.py 同样兜底清 cookie）
      clearSession();
    }
  }, [clearSession]);

  const register = useCallback(async ({ password, ...input }: RegisterInput) => {
    // Registration does not create a session.  Encrypt before the request so
    // neither the API client nor request-body logging receives plaintext.
    const passwordEnvelope = await createPasswordEnvelope(password);
    return await api.post<RegisterResponse>("/api/auth/register", {
      ...input,
      passwordEnvelope,
    });
  }, []);

  const hasRole = useCallback(
    (...roles: Role[]) => (user ? roles.includes(user.role) : false),
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      csrfToken: token,
      bootstrapping,
      login,
      logout,
      register,
      refreshSession,
      hasRole,
    }),
    [user, token, bootstrapping, login, logout, register, refreshSession, hasRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** 访问认证上下文；必须在 AuthProvider 内使用 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
