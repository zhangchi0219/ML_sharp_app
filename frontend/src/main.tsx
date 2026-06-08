import ReactDOM from "react-dom/client";

// 自托管字体（Fontsource，woff2，规避 Google CDN / GFW，离线可用）。
// family 名与 studio-web-ui tokens 对齐；中文走系统 Microsoft YaHei。
import "@fontsource/bricolage-grotesque/400.css";
import "@fontsource/bricolage-grotesque/800.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";
import "@fontsource/plus-jakarta-sans/300.css";
import "@fontsource/plus-jakarta-sans/400.css";

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/app.css";

import App from "./App";

// 不用 StrictMode：避免 dev 下 effect 双调用导致 WebGL 查看器重复初始化/释放。
ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
