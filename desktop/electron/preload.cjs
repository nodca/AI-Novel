const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aiNovelDesktop", {
  apiBaseUrl: "http://127.0.0.1:8008",
  platform: process.platform,
  pickDirectory: () => ipcRenderer.invoke("ai-novel:pick-directory")
});
