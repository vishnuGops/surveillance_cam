(() => {
  const streamImg = document.getElementById("live-stream");
  const videoStage = document.getElementById("video-stage");
  const stageOverlay = document.getElementById("stage-overlay");
  const overlayMessage = document.getElementById("overlay-message");

  const statusDot = document.getElementById("status-dot");
  const cameraTitle = document.getElementById("camera-title");
  const statusText = document.getElementById("status-text");

  const metricStatus = document.getElementById("metric-status");
  const metricResolution = document.getElementById("metric-resolution");
  const metricFps = document.getElementById("metric-fps");
  const metricViewers = document.getElementById("metric-viewers");
  const metricUptime = document.getElementById("metric-uptime");

  const btnPause = document.getElementById("btn-pause");
  const btnSnapshot = document.getElementById("btn-snapshot");
  const btnTimestamp = document.getElementById("btn-timestamp");
  const btnReconnect = document.getElementById("btn-reconnect");
  const btnFullscreen = document.getElementById("btn-fullscreen");

  let isPaused = false;
  let timestampEnabled = true;

  function formatUptime(totalSeconds) {
    const secs = Math.max(0, Math.floor(totalSeconds || 0));
    const hours = Math.floor(secs / 3600);
    const mins = Math.floor((secs % 3600) / 60);
    const rem = secs % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(hours)}:${pad(mins)}:${pad(rem)}`;
  }

  function setOverlay(message) {
    if (!message) {
      stageOverlay.hidden = true;
      return;
    }
    overlayMessage.textContent = message;
    stageOverlay.hidden = false;
  }

  function startStream() {
    isPaused = false;
    btnPause.textContent = "Pause";
    btnPause.setAttribute("aria-pressed", "false");
    setOverlay(null);
    streamImg.src = `/video_feed?t=${Date.now()}`;
  }

  function pauseStream() {
    isPaused = true;
    btnPause.textContent = "Resume";
    btnPause.setAttribute("aria-pressed", "true");
    streamImg.removeAttribute("src");
    setOverlay("Stream paused");
  }

  btnPause.addEventListener("click", () => {
    if (isPaused) {
      startStream();
    } else {
      pauseStream();
    }
  });

  btnReconnect.addEventListener("click", () => {
    startStream();
    pollStatus();
  });

  btnSnapshot.addEventListener("click", async () => {
    try {
      const response = await fetch(`/snapshot?t=${Date.now()}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`Snapshot unavailable (${response.status})`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      link.href = url;
      link.download = `surveillance_${stamp}.jpg`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      statusText.textContent = err.message || "Failed to capture snapshot";
    }
  });

  btnTimestamp.addEventListener("click", async () => {
    const nextState = !timestampEnabled;
    try {
      const response = await fetch("/api/timestamp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: nextState }),
      });
      if (!response.ok) return;
      const data = await response.json();
      timestampEnabled = Boolean(data.show_timestamp);
      btnTimestamp.textContent = `Timestamp: ${timestampEnabled ? "On" : "Off"}`;
      btnTimestamp.setAttribute("aria-pressed", String(timestampEnabled));
    } catch {
      // Ignore transient network errors; next status poll reconciles state.
    }
  });

  btnFullscreen.addEventListener("click", async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await videoStage.requestFullscreen();
      }
    } catch {
      // Fullscreen may be blocked by browser policy.
    }
  });

  document.addEventListener("fullscreenchange", () => {
    btnFullscreen.textContent = document.fullscreenElement
      ? "Exit Fullscreen"
      : "Fullscreen";
  });

  streamImg.addEventListener("error", () => {
    if (!isPaused) {
      setOverlay("Stream interrupted — click Reconnect or wait for camera.");
    }
  });

  streamImg.addEventListener("load", () => {
    if (!isPaused) {
      setOverlay(null);
    }
  });

  async function pollStatus() {
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (!response.ok) throw new Error("Server unreachable");
      const data = await response.json();

      cameraTitle.textContent = data.camera_name || "Home Cam 1";
      timestampEnabled = Boolean(data.show_timestamp);
      btnTimestamp.textContent = `Timestamp: ${timestampEnabled ? "On" : "Off"}`;
      btnTimestamp.setAttribute("aria-pressed", String(timestampEnabled));

      statusDot.classList.remove("is-online", "is-offline");
      if (data.online) {
        statusDot.classList.add("is-online");
        statusText.textContent = isPaused
          ? "Camera online (viewer paused)"
          : "Live on localhost";
        metricStatus.textContent = "Online";
        if (!isPaused) {
          setOverlay(null);
        }
      } else {
        statusDot.classList.add("is-offline");
        statusText.textContent = data.error || "Camera offline";
        metricStatus.textContent = "Offline";
        if (!isPaused) {
          setOverlay(data.error || "Waiting for webcam...");
        }
      }

      const w = data.resolution?.width || 0;
      const h = data.resolution?.height || 0;
      metricResolution.textContent = w && h ? `${w} × ${h}` : "--";
      metricFps.textContent = `${Number(data.fps || 0).toFixed(1)} FPS`;
      metricViewers.textContent = String(data.active_viewers ?? 0);
      metricUptime.textContent = formatUptime(data.uptime_seconds);
    } catch {
      statusDot.classList.remove("is-online");
      statusDot.classList.add("is-offline");
      statusText.textContent = "Server offline — waiting to reconnect...";
      metricStatus.textContent = "Disconnected";
      if (!isPaused) {
        setOverlay("Lost connection to localhost server.");
      }
    }
  }

  pollStatus();
  window.setInterval(pollStatus, 2000);
})();
