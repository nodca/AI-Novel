const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aiNovelDesktop", {
  apiBaseUrl: "http://127.0.0.1:8008",
  platform: process.platform,
  pickDirectory: () => ipcRenderer.invoke("ai-novel:pick-directory"),
  checkForUpdates: () => ipcRenderer.invoke("ai-novel:check-for-updates"),
  onUpdaterStatus: (callback) => {
    if (typeof callback !== "function") {
      return () => undefined;
    }
    const listener = (_event, payload) => {
      callback(payload);
    };
    ipcRenderer.on("ai-novel:update-status", listener);
    return () => {
      ipcRenderer.removeListener("ai-novel:update-status", listener);
    };
  }
});
