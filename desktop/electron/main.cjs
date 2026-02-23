const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const { autoUpdater } = require("electron-updater");

let backendProcess = null;
let updaterStartupTimer = null;
let updaterRetryTimer = null;

function resolveBundledBackendExe() {
  const candidate = path.join(process.resourcesPath, "backend", "ai-novel-backend.exe");
  if (fs.existsSync(candidate)) {
    return candidate;
  }
  return null;
}

function startBackend() {
  const backendEnv = {
    ...process.env,
    PYTHONIOENCODING: "utf-8"
  };

  const bundledExe = app.isPackaged ? resolveBundledBackendExe() : null;
  if (bundledExe) {
    backendProcess = spawn(bundledExe, [], {
      cwd: path.dirname(bundledExe),
      stdio: ["ignore", "pipe", "pipe"],
      env: backendEnv,
      windowsHide: true
    });
  } else {
    const pythonExe = process.env.AI_NOVEL_PYTHON || "python";
    const script = path.join(__dirname, "..", "backend", "run_backend.py");
    const cwd = path.join(__dirname, "..", "..");
    backendProcess = spawn(pythonExe, [script], {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      env: backendEnv,
      windowsHide: true
    });
  }

  backendProcess.stdout.on("data", (chunk) => {
    process.stdout.write(`[backend] ${chunk}`);
  });
  backendProcess.stderr.on("data", (chunk) => {
    process.stderr.write(`[backend] ${chunk}`);
  });
}

function stopBackend() {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
  backendProcess = null;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    backgroundColor: "#f6f2e9",
    titleBarStyle: "hiddenInset",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl) {
    win.loadURL(devUrl);
  } else {
    win.loadFile(path.join(__dirname, "..", "frontend", "dist", "index.html"));
  }

  return win;
}

function setupAutoUpdater(win) {
  if (!app.isPackaged) {
    return;
  }

  const updateChannel = String(process.env.AI_NOVEL_UPDATE_CHANNEL || "stable").toLowerCase();
  // Startup -> ask user first -> download after confirmation -> ask install after download.
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.allowPrerelease = updateChannel !== "stable";
  // Use differential download to reduce patch size when blockmap is available.
  autoUpdater.disableDifferentialDownload = false;

  let checkInFlight = false;
  let promptingUpdate = false;
  let downloadingUpdate = false;
  let deferredVersion = "";

  autoUpdater.on("checking-for-update", () => {
    console.log("[updater] checking-for-update");
  });

  autoUpdater.on("update-available", async (info) => {
    console.log("[updater] update-available", info.version);
    if (promptingUpdate || downloadingUpdate) {
      return;
    }
    const version = String(info.version || "");
    if (deferredVersion && version && deferredVersion === version) {
      console.log("[updater] skipped deferred version", version);
      return;
    }
    promptingUpdate = true;
    try {
      if (win && !win.isDestroyed()) {
        if (win.isMinimized()) {
          win.restore();
        }
        win.show();
        win.focus();
      }
      const result = await dialog.showMessageBox(win && !win.isDestroyed() ? win : undefined, {
        type: "info",
        buttons: ["立即下载更新", "稍后"],
        defaultId: 0,
        cancelId: 1,
        title: "发现新版本",
        message: version ? `检测到新版本 ${version}` : "检测到新版本",
        detail: "是否现在开始下载更新？下载完成后会再询问是否立即重启安装。"
      });
      if (result.response !== 0) {
        deferredVersion = version;
        return;
      }
      downloadingUpdate = true;
      autoUpdater.downloadUpdate().catch(async (err) => {
        downloadingUpdate = false;
        const detail = err && err.message ? err.message : "unknown";
        console.error("[updater] download failed", detail);
        await dialog.showMessageBox(win && !win.isDestroyed() ? win : undefined, {
          type: "error",
          buttons: ["知道了"],
          defaultId: 0,
          title: "更新下载失败",
          message: "未能下载更新包",
          detail: `原因：${detail}`
        });
      });
    } finally {
      promptingUpdate = false;
    }
  });

  autoUpdater.on("update-not-available", () => {
    console.log("[updater] update-not-available");
  });

  autoUpdater.on("error", (err) => {
    downloadingUpdate = false;
    console.error("[updater] error", err ? err.message : "unknown");
  });

  autoUpdater.on("download-progress", (progress) => {
    const percent = Number(progress && progress.percent) || 0;
    console.log(`[updater] download-progress ${percent.toFixed(1)}%`);
  });

  autoUpdater.on("update-downloaded", async (info) => {
    downloadingUpdate = false;
    console.log("[updater] update-downloaded", info.version);
    if (win && !win.isDestroyed()) {
      if (win.isMinimized()) {
        win.restore();
      }
      win.show();
      win.focus();
    }
    const result = await dialog.showMessageBox(win && !win.isDestroyed() ? win : undefined, {
      type: "info",
      buttons: ["立即重启更新", "稍后"],
      defaultId: 0,
      cancelId: 1,
      title: "发现新版本",
      message: `新版本 ${info.version || ""} 已下载完成`,
      detail: "立即重启会自动安装更新。"
    });
    if (result.response === 0) {
      autoUpdater.quitAndInstall();
    }
  });

  const runCheck = (reason) => {
    if (checkInFlight) {
      return;
    }
    checkInFlight = true;
    autoUpdater
      .checkForUpdates()
      .catch((err) => {
        console.error(`[updater] check failed (${reason})`, err ? err.message : "unknown");
      })
      .finally(() => {
        checkInFlight = false;
      });
  };

  updaterStartupTimer = setTimeout(() => {
    runCheck("startup");
  }, 1600);
  // Retry once on startup to avoid one-time network jitter causing a silent miss.
  updaterRetryTimer = setTimeout(() => {
    runCheck("startup-retry");
  }, 18000);
}

app.whenReady().then(() => {
  ipcMain.handle("ai-novel:pick-directory", async () => {
    const result = await dialog.showOpenDialog({
      title: "选择要导入的小说目录",
      properties: ["openDirectory"]
    });
    if (result.canceled || !result.filePaths.length) {
      return null;
    }
    return result.filePaths[0];
  });

  startBackend();
  const win = createWindow();
  setupAutoUpdater(win);
});

app.on("before-quit", () => {
  if (updaterStartupTimer) {
    clearTimeout(updaterStartupTimer);
    updaterStartupTimer = null;
  }
  if (updaterRetryTimer) {
    clearTimeout(updaterRetryTimer);
    updaterRetryTimer = null;
  }
  stopBackend();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
