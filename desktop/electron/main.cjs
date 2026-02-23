const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const { autoUpdater } = require("electron-updater");

let backendProcess = null;

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
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.allowPrerelease = updateChannel !== "stable";

  autoUpdater.on("checking-for-update", () => {
    console.log("[updater] checking-for-update");
  });

  autoUpdater.on("update-available", (info) => {
    console.log("[updater] update-available", info.version);
  });

  autoUpdater.on("update-not-available", () => {
    console.log("[updater] update-not-available");
  });

  autoUpdater.on("error", (err) => {
    console.error("[updater] error", err ? err.message : "unknown");
  });

  autoUpdater.on("download-progress", (progress) => {
    const percent = Number(progress && progress.percent) || 0;
    console.log(`[updater] download-progress ${percent.toFixed(1)}%`);
  });

  autoUpdater.on("update-downloaded", async (info) => {
    console.log("[updater] update-downloaded", info.version);
    const result = await dialog.showMessageBox(win, {
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

  setTimeout(() => {
    autoUpdater.checkForUpdatesAndNotify().catch((err) => {
      console.error("[updater] check failed", err ? err.message : "unknown");
    });
  }, 1600);
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
  stopBackend();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
