import { RouterProvider } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import { ToastProvider } from "../components";
import router from "./router";

/**
 * 应用根组件。
 * Provider 顺序：Toast（无依赖）→ Auth（401 回调清用户态触发守卫重定向）。
 */
export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </ToastProvider>
  );
}
