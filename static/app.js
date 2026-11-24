(() => {
  // ---------------- STATE ----------------
  const state = {
    activeTab: "cameras", // "cameras" | "recordings"
    layout: "grid",       // "grid" | "focus"
    focusedCameraId: null,
    cameras: [],
    storage: null,
    settings: null,
    recordings: [],
    dates: [],
    selectedClipId: null,
    checkedClipIds: new Set(),
    lastCheckedIndex: null,
    filters: {
      cameraId: "",
      date: "",
      starredOnly: false,
    },
    playbackSpeed: 1,
    renamingCameraId: null,
    streamsPaused: new Set(),
  };

  // ---------------- DOM ----------------
  const systemSummary = document.getElementById("system-summary");
  const tabCameras = document.getElementById("tab-cameras");
  const tabRecordings = document.getElementById("tab-recordings");
  const panelCameras = document.getElementById("panel-cameras");
  const panelRecordings = document.getElementById("panel-recordings");
  const badgeCameras = document.getElementById("badge-cameras");
  const badgeRecordings = document.getElementById("badge-recordings");

  const storagePillBtn = document.getElementById("btn-storage-settings");
  const storagePillMeta = document.getElementById("storage-pill-meta");
  const storageBarFill = document.getElementById("storage-bar-fill");
  const btnScanCameras = document.getElementById("btn-scan-cameras");

  const cameraWall = document.getElementById("camera-wall");
  const focusBar = document.getElementById("focus-bar");
  const focusStrip = document.getElementById("focus-strip");
  const btnBackToGrid = document.getElementById("btn-back-to-grid");
  const camerasEmpty = document.getElementById("cameras-empty");
  const cameraModeLabel = document.getElementById("camera-mode-label");
  const cameraToolbarHint = document.getElementById("camera-toolbar-hint");
  const btnLayoutGrid = document.getElementById("btn-layout-grid");
  const btnLayoutFocus = document.getElementById("btn-layout-focus");

  const recordingPlayer = document.getElementById("recording-player");
  const videoCenterOverlay = document.getElementById("video-center-overlay");
  const btnCenterAction = document.getElementById("btn-center-action");
  const centerBufferRing = document.getElementById("center-buffer-ring");
  const theaterPlaceholder = document.getElementById("theater-placeholder");
  const theaterBar = document.getElementById("theater-bar");
  const playerClipTitle = document.getElementById("player-clip-title");
  const playerClipMeta = document.getElementById("player-clip-meta");
  const playerLockedBadge = document.getElementById("player-locked-badge");
  const btnPrevClip = document.getElementById("btn-prev-clip");
  const btnNextClip = document.getElementById("btn-next-clip");
  const btnToggleStar = document.getElementById("btn-toggle-star");
  const btnDownloadClip = document.getElementById("btn-download-clip");
  const btnDeleteClip = document.getElementById("btn-delete-clip");
  const speedButtons = Array.from(document.querySelectorAll("[data-speed]"));

  const filterCamera = document.getElementById("filter-camera");
  const filterDate = document.getElementById("filter-date");
  const btnFilterStarred = document.getElementById("btn-filter-starred");
  const btnRefreshRecordings = document.getElementById("btn-refresh-recordings");
  const checkboxSelectAll = document.getElementById("checkbox-select-all");
  const clipSelectedLabel = document.getElementById("clip-selected-label");
  const btnDeleteSelected = document.getElementById("btn-delete-selected");
  const clipCountLabel = document.getElementById("clip-count-label");
  const clipStorageLabel = document.getElementById("clip-storage-label");
  const clipList = document.getElementById("clip-list");
  const recordingsEmpty = document.getElementById("recordings-empty");

  const dialogStorage = document.getElementById("dialog-storage");
  const btnCloseStorage = document.getElementById("btn-close-storage");
  const btnCancelStorage = document.getElementById("btn-cancel-storage");
  const btnRunCleanup = document.getElementById("btn-run-cleanup");
  const formStorage = document.getElementById("form-storage-settings");
  const modalStoragePath = document.getElementById("modal-storage-path");
  const modalRecUsed = document.getElementById("modal-rec-used");
  const modalRecCount = document.getElementById("modal-rec-count");
  const modalDiskFree = document.getElementById("modal-disk-free");
  const inputMaxGb = document.getElementById("input-max-gb");
  const inputMaxDays = document.getElementById("input-max-days");
  const inputSegMinutes = document.getElementById("input-seg-minutes");
  const inputAutoRecord = document.getElementById("input-auto-record");

  const dialogRename = document.getElementById("dialog-rename");
  const btnCloseRename = document.getElementById("btn-close-rename");
  const btnCancelRename = document.getElementById("btn-cancel-rename");
  const formRename = document.getElementById("form-rename");
  const inputCameraName = document.getElementById("input-camera-name");

  const toastEl = document.getElementById("toast");
  let toastTimer = null;

  // ---------------- HELPERS ----------------
  function showToast(message) {
    toastEl.textContent = message.toUpperCase();
    toastEl.hidden = false;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
      toastEl.hidden = true;
    }, 3200);
  }

  function formatBytes(bytes) {
    const val = Number(bytes || 0);
    if (val >= 1024 ** 3) return `${(val / 1024 ** 3).toFixed(2)} GB`;
    if (val >= 1024 ** 2) return `${(val / 1024 ** 2).toFixed(1)} MB`;
    if (val >= 1024) return `${(val / 1024).toFixed(0)} KB`;
    return `${val} B`;
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds || 0)));
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function formatChannel(index) {
    return `CH-${String(Number(index) + 1).padStart(2, "0")}`;
  }

  function formatClipTime(isoString) {
    if (!isoString) return "--";
    const dt = new Date(isoString);
    if (Number.isNaN(dt.getTime())) return isoString;
    return dt.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function formatClipDateTime(isoString) {
    if (!isoString) return "--";
    const dt = new Date(isoString);
    if (Number.isNaN(dt.getTime())) return isoString;
    return dt.toLocaleString([], {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (body.detail) detail = body.detail;
      } catch {
        // ignore
      }
      throw new Error(detail);
    }
    return response.json();
  }

  // ---------------- TAB NAVIGATION ----------------
  function setActiveTab(tab) {
    state.activeTab = tab;
    const isCameras = tab === "cameras";

    tabCameras.classList.toggle("is-active", isCameras);
    tabCameras.setAttribute("aria-selected", String(isCameras));
    panelCameras.hidden = !isCameras;

    tabRecordings.classList.toggle("is-active", !isCameras);
    tabRecordings.setAttribute("aria-selected", String(!isCameras));
    panelRecordings.hidden = isCameras;

    syncStreamSources();
    if (!isCameras) {
      fetchRecordings();
    }
  }

  tabCameras.addEventListener("click", () => setActiveTab("cameras"));
  tabRecordings.addEventListener("click", () => setActiveTab("recordings"));

  function syncStreamSources() {
    const cards = cameraWall.querySelectorAll(".cam-card");
    cards.forEach((card) => {
      const camId = card.dataset.camId;
      const img = card.querySelector("img.cam-stream-img");
      if (!img) return;
      const isFocusedHidden =
        state.layout === "focus" && state.focusedCameraId !== camId;
      const shouldStream =
        state.activeTab === "cameras" &&
        !state.streamsPaused.has(camId) &&
        !isFocusedHidden;

      if (shouldStream) {
        if (!img.dataset.streaming) {
          img.src = `/api/cameras/${encodeURIComponent(camId)}/stream?t=${Date.now()}`;
          img.dataset.streaming = "1";
        }
      } else if (img.dataset.streaming) {
        img.removeAttribute("src");
        delete img.dataset.streaming;
      }
    });
  }

  // ---------------- LAYOUT MODE (GRID <-> FOCUS) ----------------
  function setLayout(mode, focusId = null) {
    state.layout = mode;
    if (focusId) {
      state.focusedCameraId = focusId;
    } else if (!state.focusedCameraId && state.cameras.length > 0) {
      state.focusedCameraId = state.cameras[0].id;
    }

    cameraWall.dataset.layout = mode;
    btnLayoutGrid.classList.toggle("is-active", mode === "grid");
    btnLayoutGrid.setAttribute("aria-pressed", String(mode === "grid"));
    btnLayoutFocus.classList.toggle("is-active", mode === "focus");
    btnLayoutFocus.setAttribute("aria-pressed", String(mode === "focus"));

    updateFocusClasses();
    syncStreamSources();
    updateCameraToolbarCopy();
  }

  function updateCameraToolbarCopy() {
    const mins = Math.round((state.settings?.segment_duration_seconds || 300) / 60);
    const dataDir = state.settings?.data_dir || "C:\\SurveillanceData";
    if (state.layout === "focus") {
      const focused = state.cameras.find((c) => c.id === state.focusedCameraId);
      cameraModeLabel.textContent = focused
        ? `FOCUS // ${formatChannel(focused.index)} ${focused.name.toUpperCase()}`
        : "FOCUS // THEATER";
      cameraToolbarHint.textContent = `SINGLE-FEED LOCK · ${mins}-MIN H.264 LOOPS → ${dataDir}`;
    } else {
      cameraModeLabel.textContent = "MATRIX // GRID VIEW";
      cameraToolbarHint.textContent = `CLICK ANY CAMERA CARD TO FOCUS · ${mins}-MIN H.264 LOOPS → ${dataDir}`;
    }
  }

  function updateFocusClasses() {
    cameraWall.querySelectorAll(".cam-card").forEach((card) => {
      card.classList.toggle(
        "is-focused",
        card.dataset.camId === state.focusedCameraId
      );
    });
    renderFocusBar();
  }

  function renderFocusBar() {
    const inFocus = state.layout === "focus" && state.cameras.length > 0;
    focusBar.hidden = !inFocus;
    if (!inFocus) return;

    focusStrip.innerHTML = "";
    state.cameras.forEach((cam) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip-btn";
      if (cam.id === state.focusedCameraId) {
        btn.classList.add("is-active");
      }
      btn.textContent = `${formatChannel(cam.index)} // ${cam.name.toUpperCase()}`;
      btn.addEventListener("click", () => setLayout("focus", cam.id));
      focusStrip.appendChild(btn);
    });
  }

  btnLayoutGrid.addEventListener("click", () => setLayout("grid"));
  btnLayoutFocus.addEventListener("click", () => setLayout("focus"));
  btnBackToGrid.addEventListener("click", () => setLayout("grid"));

  // ---------------- CAMERA WALL RENDERING ----------------
  function createCameraCard(cam) {
    const card = document.createElement("article");
    card.className = "cam-card";
    card.dataset.camId = cam.id;

    card.innerHTML = `
      <div class="cam-header" data-focus-trigger="1" title="Click to focus camera">
        <div class="cam-title-cluster">
          <span class="cam-channel" data-field="channel"></span>
          <h2 class="cam-name" data-field="name"></h2>
        </div>
        <div class="cam-header-status">
          <span class="hud-dot" data-field="dot"></span>
          <span data-field="hud-status">INIT</span>
        </div>
      </div>

      <div class="cam-stage" data-focus-trigger="1">
        <span class="reticle reticle-tl" aria-hidden="true"></span>
        <span class="reticle reticle-tr" aria-hidden="true"></span>
        <span class="reticle reticle-bl" aria-hidden="true"></span>
        <span class="reticle reticle-br" aria-hidden="true"></span>

        <img
          class="cam-stream-img"
          alt=""
          width="1280"
          height="720"
          decoding="async"
        />

        <div class="cam-hud-top">
          <div class="cam-hud-left">
            <span class="hud-pill hud-rec" data-field="rec-pill" hidden>
              <span class="rec-pulse" aria-hidden="true"></span>
              <span data-field="rec-timer">REC 00:00 / 05:00</span>
            </span>
            <span
              class="hud-pill hud-nv"
              data-field="nv-pill"
              title="Night Vision Active"
              aria-label="Night Vision Active"
              hidden
            >
              <svg class="hud-nv-eye" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M2 12C4.5 7.5 8 5.5 12 5.5C16 5.5 19.5 7.5 22 12C19.5 16.5 16 18.5 12 18.5C8 18.5 4.5 16.5 2 12Z"
                  stroke="currentColor"
                  stroke-width="1.9"
                />
                <circle cx="12" cy="12" r="3.2" fill="currentColor" />
              </svg>
              <span>NV</span>
            </span>
          </div>
          <span class="hud-pill" data-field="hud-metrics">--</span>
        </div>

        <span class="focus-cue" aria-hidden="true">[ CLICK TO FOCUS ]</span>
        <div class="cam-overlay-msg" data-field="overlay" hidden>ACQUIRING SIGNAL...</div>
        <div class="cam-loop-progress" aria-hidden="true">
          <div class="cam-loop-fill" data-field="loop-fill"></div>
        </div>
      </div>

      <div class="cam-footer">
        <span class="cam-sub" data-field="sub"></span>
        <div class="cam-actions">
          <button type="button" class="btn btn-sm" data-action="record">REC</button>
          <button type="button" class="btn btn-sm" data-action="nightmode">NV:AUTO</button>
          <button type="button" class="btn btn-sm" data-action="snapshot">SNAP</button>
          <button type="button" class="btn btn-sm" data-action="rename">RENAME</button>
          <button type="button" class="btn btn-sm" data-action="fullscreen">FULL</button>
        </div>
      </div>
    `;

    // Clicking card header or viewport in Grid mode enters Focus mode
    card.querySelectorAll('[data-focus-trigger="1"]').forEach((el) => {
      el.addEventListener("click", () => {
        if (state.layout === "grid") {
          setLayout("focus", cam.id);
        }
      });
    });

    card.querySelector('[data-action="record"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      const current = state.cameras.find((c) => c.id === cam.id);
      if (!current) return;
      const nextRec = !current.recording.enabled;
      try {
        await apiJson(`/api/cameras/${encodeURIComponent(cam.id)}`, {
          method: "PATCH",
          body: JSON.stringify({ recording: nextRec }),
        });
        showToast(
          nextRec
            ? `Recording engaged // ${current.name}`
            : `Recording stopped // ${current.name} loop archived`
        );
        await fetchCameras();
      } catch (err) {
        showToast(err.message);
      }
    });

    card.querySelector('[data-action="nightmode"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      const current = state.cameras.find((c) => c.id === cam.id);
      if (!current) return;
      const order = ["auto", "on", "off"];
      const currMode = current.night_vision?.mode || "auto";
      const nextMode = order[(order.indexOf(currMode) + 1) % order.length];
      try {
        await apiJson(`/api/cameras/${encodeURIComponent(cam.id)}`, {
          method: "PATCH",
          body: JSON.stringify({ night_mode: nextMode }),
        });
        showToast(`Night vision // ${current.name} → ${nextMode.toUpperCase()}`);
        await fetchCameras();
      } catch (err) {
        showToast(err.message);
      }
    });

    card.querySelector('[data-action="snapshot"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      const current = state.cameras.find((c) => c.id === cam.id);
      try {
        const resp = await fetch(
          `/api/cameras/${encodeURIComponent(cam.id)}/snapshot?save=1&t=${Date.now()}`,
          { cache: "no-store" }
        );
        if (!resp.ok) throw new Error("Snapshot not ready");
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        const stamp = new Date().toISOString().replace(/[:.]/g, "-");
        a.href = url;
        a.download = `EYEz_${cam.id}_${stamp}.jpg`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        showToast(`Snapshot captured // ${current ? current.name : cam.id}`);
      } catch (err) {
        showToast(err.message || "Failed to capture snapshot");
      }
    });

    card.querySelector('[data-action="rename"]').addEventListener("click", (e) => {
      e.stopPropagation();
      const current = state.cameras.find((c) => c.id === cam.id);
      state.renamingCameraId = cam.id;
      inputCameraName.value = current ? current.name : cam.name;
      dialogRename.showModal();
      inputCameraName.select();
    });

    card.querySelector('[data-action="fullscreen"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      const stage = card.querySelector(".cam-stage");
      try {
        if (document.fullscreenElement) {
          await document.exitFullscreen();
        } else {
          await stage.requestFullscreen();
        }
      } catch {
        // ignore browser policy errors
      }
    });

    return card;
  }

  function updateCameraCard(card, cam) {
    const channelEl = card.querySelector('[data-field="channel"]');
    const dot = card.querySelector('[data-field="dot"]');
    const hudStatus = card.querySelector('[data-field="hud-status"]');
    const recPill = card.querySelector('[data-field="rec-pill"]');
    const recTimer = card.querySelector('[data-field="rec-timer"]');
    const nvPill = card.querySelector('[data-field="nv-pill"]');
    const hudMetrics = card.querySelector('[data-field="hud-metrics"]');
    const overlay = card.querySelector('[data-field="overlay"]');
    const loopFill = card.querySelector('[data-field="loop-fill"]');
    const nameEl = card.querySelector('[data-field="name"]');
    const imgEl = card.querySelector("img.cam-stream-img");
    const subEl = card.querySelector('[data-field="sub"]');

    const btnRec = card.querySelector('[data-action="record"]');
    const btnNv = card.querySelector('[data-action="nightmode"]');

    channelEl.textContent = formatChannel(cam.index);
    nameEl.textContent = cam.name;
    if (imgEl) imgEl.alt = `Live feed from ${cam.name}`;

    const resText =
      cam.resolution?.width && cam.resolution?.height
        ? `${cam.resolution.width}×${cam.resolution.height}`
        : "--";
    const fpsText = `${Number(cam.fps || 0).toFixed(1)} FPS`;
    hudMetrics.textContent = `${resText} // ${fpsText}`;
    subEl.textContent = `USB:${cam.index} · ${cam.active_viewers} VIEWER${
      cam.active_viewers === 1 ? "" : "S"
    } · ${cam.recording.segments_completed} SAVED`;

    dot.classList.toggle("is-online", Boolean(cam.online));
    dot.classList.toggle("is-offline", !cam.online);
    hudStatus.textContent = cam.online ? "ONLINE" : "OFFLINE";

    if (!cam.online) {
      overlay.textContent = (cam.error || "WAITING FOR SIGNAL...").toUpperCase();
      overlay.hidden = false;
    } else {
      overlay.hidden = true;
    }

    const recActive = Boolean(cam.recording?.active);
    const recEnabled = Boolean(cam.recording?.enabled);
    recPill.hidden = !recActive;

    const segDur = Math.max(1, cam.recording?.segment_duration_seconds || 300);
    const segElapsed = Math.min(segDur, cam.recording?.segment_elapsed_seconds || 0);
    recTimer.textContent = `REC ${formatDuration(segElapsed)} / ${formatDuration(segDur)}`;
    const pct = recActive ? Math.min(100, (segElapsed / segDur) * 100) : 0;
    loopFill.style.setProperty("--loop-pct", `${pct.toFixed(1)}%`);

    btnRec.textContent = recEnabled ? "● REC" : "REC OFF";
    btnRec.classList.toggle("btn-rec-active", recEnabled);

    const nvMode = (cam.night_vision?.mode || "auto").toUpperCase();
    const nvActive = Boolean(cam.night_vision?.active) && Boolean(cam.online);
    nvPill.hidden = !nvActive;
    btnNv.textContent = `NV:${nvMode}`;
    btnNv.classList.toggle("btn-nv-active", nvActive);
  }

  function ensureExpansionSlot() {
    let slot = cameraWall.querySelector(".cam-slot-card");
    const shouldShow = state.cameras.length === 1;
    if (!shouldShow) {
      if (slot) slot.remove();
      return;
    }
    if (!slot) {
      slot = document.createElement("button");
      slot.type = "button";
      slot.className = "cam-slot-card";
      slot.innerHTML = `
        <span class="cam-slot-code">[ CH-02 // STANDBY SLOT ]</span>
        <span class="cam-slot-title">+ ADD USB CAMERA NODE</span>
        <span class="cam-slot-desc">Plug in another USB webcam and click here to scan and expand your EYEz grid matrix.</span>
      `;
      slot.addEventListener("click", () => scanUsbCameras());
      cameraWall.appendChild(slot);
    } else {
      // Keep expansion slot last in grid
      cameraWall.appendChild(slot);
    }
  }

  function renderCameras() {
    const cams = state.cameras;
    badgeCameras.textContent = String(cams.length);
    cameraWall.dataset.count = String(cams.length);
    camerasEmpty.hidden = cams.length > 0;

    if (!state.focusedCameraId && cams.length > 0) {
      state.focusedCameraId = cams[0].id;
    }

    cameraWall.querySelectorAll(".cam-card").forEach((card) => {
      const id = card.dataset.camId;
      if (!cams.some((c) => c.id === id)) {
        card.remove();
      }
    });

    cams.forEach((cam) => {
      let card = cameraWall.querySelector(
        `.cam-card[data-cam-id="${CSS.escape(cam.id)}"]`
      );
      if (!card) {
        card = createCameraCard(cam);
        cameraWall.appendChild(card);
      }
      updateCameraCard(card, cam);
    });

    ensureExpansionSlot();
    updateFocusClasses();
    syncStreamSources();
    updateCameraToolbarCopy();

    const onlineCount = cams.filter((c) => c.online).length;
    const recCount = cams.filter((c) => c.recording?.active).length;
    systemSummary.textContent = cams.length
      ? `NODES: ${onlineCount}/${cams.length} ONLINE // REC: ${recCount} ACTIVE`
      : "NODES: 00 // NO USB CAMERAS DETECTED";

    populateCameraFilterOptions();
  }

  function populateCameraFilterOptions() {
    const previous = filterCamera.value;
    const known = new Map();
    state.cameras.forEach((c) => known.set(c.id, c.name));
    state.recordings.forEach((r) => {
      if (!known.has(r.camera_id)) {
        known.set(r.camera_id, r.camera_name || r.camera_id);
      }
    });

    filterCamera.innerHTML = `<option value="">ALL CAMERAS</option>`;
    known.forEach((name, id) => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = name.toUpperCase();
      filterCamera.appendChild(opt);
    });
    if ([...known.keys()].includes(previous)) {
      filterCamera.value = previous;
    }
  }

  // ---------------- STORAGE HUD ----------------
  function renderStorageHud() {
    const st = state.storage;
    if (!st) return;

    badgeRecordings.textContent = String(st.recordings_count || 0);
    const usedBytes = st.recordings_bytes || 0;
    const capGb = Number(st.max_storage_gb || 0);

    if (capGb > 0) {
      storagePillMeta.textContent = `${formatBytes(usedBytes)} / ${capGb} GB`;
      const pct = Math.min(100, (usedBytes / (capGb * 1024 ** 3)) * 100);
      storageBarFill.style.setProperty("--usage-pct", `${pct.toFixed(1)}%`);
    } else {
      storagePillMeta.textContent = `${formatBytes(usedBytes)} // UNLIMITED`;
      storageBarFill.style.setProperty("--usage-pct", "18%");
    }

    modalStoragePath.textContent = st.data_dir || "C:\\SurveillanceData";
    modalRecUsed.textContent = formatBytes(usedBytes);
    modalRecCount.textContent = `${st.recordings_count} (${st.locked_count} ★)`;
    modalDiskFree.textContent = formatBytes(st.disk_free_bytes);
  }

  // ---------------- RECORDINGS ARCHIVE ----------------
  let pauseRevealTimer = null;
  let playerControlsVisible = false;
  let playerBuffering = false;

  function clearPauseRevealTimer() {
    window.clearTimeout(pauseRevealTimer);
    pauseRevealTimer = null;
  }

  function syncPlayerOverlay() {
    const hasClip = Boolean(state.selectedClipId);
    videoCenterOverlay.hidden = !hasClip;
    if (!hasClip) {
      clearPauseRevealTimer();
      playerControlsVisible = false;
      playerBuffering = false;
      centerBufferRing.hidden = true;
      return;
    }

    const paused = recordingPlayer.paused || recordingPlayer.ended;
    const showBuffer = playerBuffering && !paused;

    videoCenterOverlay.classList.toggle("is-paused", paused);
    videoCenterOverlay.classList.toggle("is-playing", !paused);
    videoCenterOverlay.classList.toggle(
      "is-controls-visible",
      !paused && playerControlsVisible
    );
    videoCenterOverlay.classList.toggle("is-buffering", showBuffer);
    centerBufferRing.hidden = !showBuffer;

    btnCenterAction.setAttribute(
      "aria-label",
      paused ? "Play video" : "Pause video"
    );
  }

  function revealPauseBriefly() {
    playerControlsVisible = true;
    syncPlayerOverlay();
    clearPauseRevealTimer();
    pauseRevealTimer = window.setTimeout(() => {
      if (!recordingPlayer.paused) {
        playerControlsVisible = false;
        syncPlayerOverlay();
      }
    }, 2600);
  }

  // Click on Play / Pause button in center
  btnCenterAction.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!state.selectedClipId) return;

    if (recordingPlayer.paused || recordingPlayer.ended) {
      playerControlsVisible = false;
      clearPauseRevealTimer();
      if (recordingPlayer.readyState < 3) {
        playerBuffering = true;
      }
      recordingPlayer.play().catch(() => {
        playerBuffering = false;
        syncPlayerOverlay();
      });
      syncPlayerOverlay();
    } else if (playerControlsVisible) {
      // Clicking Pause while Pause icon is shown pauses playback
      clearPauseRevealTimer();
      playerControlsVisible = false;
      playerBuffering = false;
      recordingPlayer.pause();
      syncPlayerOverlay();
    }
  });

  // Tapping video area while playing reveals Pause icon (continues playing)
  videoCenterOverlay.addEventListener("click", () => {
    if (!state.selectedClipId) return;
    if (recordingPlayer.paused || recordingPlayer.ended) {
      return;
    }
    if (playerControlsVisible) {
      clearPauseRevealTimer();
      playerControlsVisible = false;
      syncPlayerOverlay();
    } else {
      revealPauseBriefly();
    }
  });

  recordingPlayer.addEventListener("play", () => {
    clearPauseRevealTimer();
    playerControlsVisible = false;
    if (recordingPlayer.readyState < 3) {
      playerBuffering = true;
    }
    syncPlayerOverlay();
  });

  recordingPlayer.addEventListener("playing", () => {
    playerBuffering = false;
    playerControlsVisible = false;
    syncPlayerOverlay();
  });

  recordingPlayer.addEventListener("canplay", () => {
    playerBuffering = false;
    syncPlayerOverlay();
  });

  recordingPlayer.addEventListener("waiting", () => {
    if (!recordingPlayer.paused) {
      playerBuffering = true;
      syncPlayerOverlay();
    }
  });

  recordingPlayer.addEventListener("stalled", () => {
    if (!recordingPlayer.paused) {
      playerBuffering = true;
      syncPlayerOverlay();
    }
  });

  recordingPlayer.addEventListener("pause", () => {
    clearPauseRevealTimer();
    playerControlsVisible = false;
    playerBuffering = false;
    syncPlayerOverlay();
  });

  recordingPlayer.addEventListener("ended", () => {
    clearPauseRevealTimer();
    playerControlsVisible = false;
    playerBuffering = false;
    syncPlayerOverlay();
  });

  recordingPlayer.addEventListener("error", () => {
    playerBuffering = false;
    syncPlayerOverlay();
  });

  function selectClip(clipId) {
    const clip = state.recordings.find((r) => r.id === clipId);
    state.selectedClipId = clip ? clip.id : null;
    clearPauseRevealTimer();
    playerControlsVisible = false;
    playerBuffering = false;

    clipList.querySelectorAll(".clip-item").forEach((btn) => {
      btn.classList.toggle("is-selected", btn.dataset.clipId === state.selectedClipId);
    });

    if (!clip) {
      recordingPlayer.pause();
      recordingPlayer.removeAttribute("src");
      recordingPlayer.removeAttribute("poster");
      recordingPlayer.load();
      videoCenterOverlay.hidden = true;
      theaterPlaceholder.hidden = false;
      theaterBar.hidden = true;
      return;
    }

    theaterPlaceholder.hidden = true;
    theaterBar.hidden = false;

    recordingPlayer.pause();
    if (clip.thumbnail_url) {
      recordingPlayer.poster = clip.thumbnail_url;
    } else {
      recordingPlayer.removeAttribute("poster");
    }

    recordingPlayer.src = clip.video_url;
    recordingPlayer.playbackRate = state.playbackSpeed;
    recordingPlayer.load();
    syncPlayerOverlay();

    updatePlayerHeader(clip);
  }

  function updatePlayerHeader(clip) {
    playerClipTitle.textContent = `${clip.camera_name} // ${formatClipDateTime(
      clip.started_at
    )}`;
    const res = clip.width && clip.height ? `${clip.width}×${clip.height}` : "--";
    playerClipMeta.textContent = `DUR ${formatDuration(
      clip.duration_seconds
    )} // ${formatBytes(clip.size_bytes)} // ${res} // ${clip.filename}`;

    playerLockedBadge.hidden = !clip.locked;
    btnToggleStar.textContent = clip.locked ? "★ LOCKED" : "☆ STAR";
    btnToggleStar.classList.toggle("btn-star-active", Boolean(clip.locked));
    btnToggleStar.setAttribute("aria-pressed", String(Boolean(clip.locked)));

    btnDownloadClip.href = clip.download_url;
    btnDownloadClip.download = `EYEz_${clip.camera_id}_${clip.date}_${clip.filename}`;

    btnDeleteClip.disabled = Boolean(clip.locked);
    btnDeleteClip.title = clip.locked
      ? "Unstar clip before deleting"
      : "Delete this recording";

    const idx = state.recordings.findIndex((r) => r.id === clip.id);
    btnPrevClip.disabled = idx <= 0;
    btnNextClip.disabled = idx < 0 || idx >= state.recordings.length - 1;
  }

  function getDeletableClips() {
    return state.recordings.filter((r) => !r.locked);
  }

  function syncBulkSelectionUi() {
    const deletable = getDeletableClips();
    const deletableIds = new Set(deletable.map((r) => r.id));

    // Prune any checked IDs that are no longer visible or became locked
    for (const id of Array.from(state.checkedClipIds)) {
      if (!deletableIds.has(id)) {
        state.checkedClipIds.delete(id);
      }
    }

    const checkedCount = state.checkedClipIds.size;
    const totalDeletable = deletable.length;

    clipSelectedLabel.textContent = `${checkedCount} SELECTED`;
    clipSelectedLabel.classList.toggle("has-selection", checkedCount > 0);
    btnDeleteSelected.disabled = checkedCount === 0;
    btnDeleteSelected.title =
      checkedCount > 0
        ? `Delete ${checkedCount} selected recording(s)`
        : "Select unlocked recordings to delete";

    checkboxSelectAll.disabled = totalDeletable === 0;
    checkboxSelectAll.checked =
      totalDeletable > 0 && checkedCount === totalDeletable;
    checkboxSelectAll.indeterminate =
      checkedCount > 0 && checkedCount < totalDeletable;

    clipList.querySelectorAll(".clip-row").forEach((row) => {
      const id = row.dataset.clipId;
      const isChecked = state.checkedClipIds.has(id);
      row.classList.toggle("is-checked", isChecked);
      const cb = row.querySelector("input.clip-check");
      if (cb) cb.checked = isChecked;
    });
  }

  function renderRecordingsList() {
    const recs = state.recordings;
    const totalBytes = recs.reduce((acc, r) => acc + (r.size_bytes || 0), 0);

    clipCountLabel.textContent = `${recs.length} CLIP${recs.length === 1 ? "" : "S"}`;
    clipStorageLabel.textContent = formatBytes(totalBytes);
    recordingsEmpty.hidden = recs.length > 0;

    const currentDate = filterDate.value;
    filterDate.innerHTML = `<option value="">ALL DATES</option>`;
    state.dates.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      filterDate.appendChild(opt);
    });
    if (state.dates.includes(currentDate)) {
      filterDate.value = currentDate;
    }

    populateCameraFilterOptions();

    clipList.innerHTML = "";
    recs.forEach((clip, index) => {
      const li = document.createElement("li");
      li.className = "clip-row";
      li.dataset.clipId = clip.id;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "clip-check";
      cb.disabled = Boolean(clip.locked);
      cb.checked = !clip.locked && state.checkedClipIds.has(clip.id);
      cb.setAttribute(
        "aria-label",
        clip.locked
          ? `${clip.camera_name} ${clip.filename} (locked)`
          : `Select ${clip.camera_name} ${clip.filename}`
      );
      if (clip.locked) {
        cb.title = "Locked clip — unstar to select for deletion";
      }

      cb.addEventListener("click", (e) => {
        e.stopPropagation();
        if (clip.locked) return;
        const targetChecked = cb.checked;

        // Shift+Click range selection across visible unlocked clips
        if (e.shiftKey && state.lastCheckedIndex !== null) {
          const start = Math.min(state.lastCheckedIndex, index);
          const end = Math.max(state.lastCheckedIndex, index);
          for (let i = start; i <= end; i += 1) {
            const item = state.recordings[i];
            if (item && !item.locked) {
              if (targetChecked) {
                state.checkedClipIds.add(item.id);
              } else {
                state.checkedClipIds.delete(item.id);
              }
            }
          }
        } else if (targetChecked) {
          state.checkedClipIds.add(clip.id);
        } else {
          state.checkedClipIds.delete(clip.id);
        }

        state.lastCheckedIndex = index;
        syncBulkSelectionUi();
      });

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "clip-item";
      btn.dataset.clipId = clip.id;
      if (clip.id === state.selectedClipId) {
        btn.classList.add("is-selected");
      }

      const thumbMarkup = clip.thumbnail_url
        ? `<img src="${clip.thumbnail_url}" alt="" width="100" height="56" loading="lazy" />`
        : "";
      const starTag = clip.locked
        ? `<span class="clip-star-tag" aria-label="Locked">★</span>`
        : "";

      btn.innerHTML = `
        <span class="clip-thumb-wrap">
          ${thumbMarkup}
          ${starTag}
          <span class="clip-duration-tag">${formatDuration(clip.duration_seconds)}</span>
        </span>
        <span class="clip-item-info">
          <span class="clip-item-cam"></span>
          <span class="clip-item-time">${clip.date} · ${formatClipTime(clip.started_at)}</span>
          <span class="clip-item-size">${formatBytes(clip.size_bytes)}</span>
        </span>
      `;
      btn.querySelector(".clip-item-cam").textContent = clip.camera_name;
      btn.addEventListener("click", () => selectClip(clip.id));

      li.appendChild(cb);
      li.appendChild(btn);
      clipList.appendChild(li);
    });

    syncBulkSelectionUi();

    if (recs.length === 0) {
      selectClip(null);
    } else if (state.selectedClipId) {
      const existing = recs.find((r) => r.id === state.selectedClipId);
      if (existing) {
        updatePlayerHeader(existing);
      } else {
        selectClip(null);
      }
    }
  }

  speedButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const speed = Number(btn.dataset.speed || 1);
      state.playbackSpeed = speed;
      recordingPlayer.playbackRate = speed;
      speedButtons.forEach((b) =>
        b.classList.toggle("is-active", Number(b.dataset.speed) === speed)
      );
    });
  });

  btnPrevClip.addEventListener("click", () => {
    const idx = state.recordings.findIndex((r) => r.id === state.selectedClipId);
    if (idx > 0) selectClip(state.recordings[idx - 1].id);
  });

  btnNextClip.addEventListener("click", () => {
    const idx = state.recordings.findIndex((r) => r.id === state.selectedClipId);
    if (idx >= 0 && idx < state.recordings.length - 1) {
      selectClip(state.recordings[idx + 1].id);
    }
  });

  btnToggleStar.addEventListener("click", async () => {
    const clip = state.recordings.find((r) => r.id === state.selectedClipId);
    if (!clip) return;
    try {
      const data = await apiJson(
        `/api/recordings/lock/${encodeURI(clip.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ locked: !clip.locked }),
        }
      );
      const updated = data.recording;
      const idx = state.recordings.findIndex((r) => r.id === clip.id);
      if (idx >= 0) state.recordings[idx] = updated;
      renderRecordingsList();
      showToast(
        updated.locked
          ? "Clip locked // protected from purge"
          : "Clip lock removed"
      );
      fetchCameras();
    } catch (err) {
      showToast(err.message);
    }
  });

  btnDeleteClip.addEventListener("click", async () => {
    const clip = state.recordings.find((r) => r.id === state.selectedClipId);
    if (!clip || clip.locked) return;
    if (!window.confirm(`Delete recording ${clip.filename} from ${clip.camera_name}?`)) {
      return;
    }
    try {
      await apiJson(`/api/recordings/item/${encodeURI(clip.id)}`, {
        method: "DELETE",
      });
      selectClip(null);
      showToast("Recording purged");
      await fetchRecordings();
      await fetchCameras();
    } catch (err) {
      showToast(err.message);
    }
  });

  filterCamera.addEventListener("change", () => {
    state.filters.cameraId = filterCamera.value;
    fetchRecordings();
  });

  filterDate.addEventListener("change", () => {
    state.filters.date = filterDate.value;
    fetchRecordings();
  });

  btnFilterStarred.addEventListener("click", () => {
    state.filters.starredOnly = !state.filters.starredOnly;
    btnFilterStarred.classList.toggle("is-active", state.filters.starredOnly);
    btnFilterStarred.setAttribute("aria-pressed", String(state.filters.starredOnly));
    fetchRecordings();
  });

  btnRefreshRecordings.addEventListener("click", () => {
    fetchRecordings();
    showToast("Archive refreshed");
  });

  checkboxSelectAll.addEventListener("change", () => {
    const deletable = getDeletableClips();
    if (checkboxSelectAll.checked) {
      deletable.forEach((c) => state.checkedClipIds.add(c.id));
    } else {
      state.checkedClipIds.clear();
    }
    state.lastCheckedIndex = null;
    syncBulkSelectionUi();
  });

  btnDeleteSelected.addEventListener("click", async () => {
    const ids = Array.from(state.checkedClipIds);
    if (ids.length === 0) return;
    if (
      !window.confirm(
        `Delete ${ids.length} selected recording${ids.length === 1 ? "" : "s"}?`
      )
    ) {
      return;
    }

    btnDeleteSelected.disabled = true;
    try {
      const data = await apiJson("/api/recordings/bulk-delete", {
        method: "POST",
        body: JSON.stringify({ ids }),
      });
      const deletedSet = new Set(data.deleted || []);
      if (state.selectedClipId && deletedSet.has(state.selectedClipId)) {
        selectClip(null);
      }
      state.checkedClipIds.clear();
      state.lastCheckedIndex = null;
      const count = data.deleted_count || 0;
      const skipped = (data.skipped_locked || []).length;
      showToast(
        skipped > 0
          ? `Purged ${count} clip(s) // ${skipped} locked skipped`
          : `Purged ${count} recording${count === 1 ? "" : "s"}`
      );
      await fetchRecordings();
      await fetchCameras();
    } catch (err) {
      showToast(err.message || "Bulk delete failed");
      syncBulkSelectionUi();
    }
  });

  // ---------------- DIALOGS ----------------
  storagePillBtn.addEventListener("click", () => {
    if (state.settings) {
      inputMaxGb.value = String(state.settings.max_storage_gb ?? 50);
      inputMaxDays.value = String(state.settings.max_retention_days ?? 7);
      inputSegMinutes.value = String(
        Math.max(1, Math.round((state.settings.segment_duration_seconds || 300) / 60))
      );
      inputAutoRecord.checked = Boolean(state.settings.auto_record_new_cameras);
    }
    renderStorageHud();
    dialogStorage.showModal();
  });

  btnCloseStorage.addEventListener("click", () => dialogStorage.close());
  btnCancelStorage.addEventListener("click", () => dialogStorage.close());

  formStorage.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const payload = {
        max_storage_gb: Number(inputMaxGb.value),
        max_retention_days: Number(inputMaxDays.value),
        segment_duration_seconds: Math.max(1, Number(inputSegMinutes.value)) * 60,
        auto_record_new_cameras: inputAutoRecord.checked,
      };
      const data = await apiJson("/api/storage/settings", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      state.settings = data.settings;
      state.storage = data.storage;
      renderStorageHud();
      renderCameras();
      dialogStorage.close();
      showToast("Vault retention policy updated");
    } catch (err) {
      showToast(err.message);
    }
  });

  btnRunCleanup.addEventListener("click", async () => {
    try {
      const data = await apiJson("/api/storage/cleanup", { method: "POST" });
      state.storage = data.storage;
      renderStorageHud();
      if (state.activeTab === "recordings") {
        fetchRecordings();
      }
      const n = data.cleanup?.deleted_count || 0;
      showToast(
        n > 0
          ? `Purged ${n} clip(s) // ${formatBytes(data.cleanup.reclaimed_bytes)} freed`
          : "Vault within retention limits"
      );
    } catch (err) {
      showToast(err.message);
    }
  });

  btnCloseRename.addEventListener("click", () => dialogRename.close());
  btnCancelRename.addEventListener("click", () => dialogRename.close());

  formRename.addEventListener("submit", async (e) => {
    e.preventDefault();
    const camId = state.renamingCameraId;
    const newName = inputCameraName.value.trim();
    if (!camId || !newName) return;
    try {
      await apiJson(`/api/cameras/${encodeURIComponent(camId)}`, {
        method: "PATCH",
        body: JSON.stringify({ name: newName }),
      });
      dialogRename.close();
      showToast(`Node renamed // ${newName}`);
      await fetchCameras();
    } catch (err) {
      showToast(err.message);
    }
  });

  async function scanUsbCameras() {
    btnScanCameras.disabled = true;
    try {
      const data = await apiJson("/api/cameras/scan", { method: "POST" });
      state.cameras = data.cameras || [];
      renderCameras();
      showToast(`USB scan complete // ${state.cameras.length} node(s) active`);
    } catch (err) {
      showToast(err.message);
    } finally {
      btnScanCameras.disabled = false;
    }
  }

  btnScanCameras.addEventListener("click", () => scanUsbCameras());

  // ---------------- DATA FETCHING ----------------
  async function fetchCameras() {
    try {
      const data = await apiJson("/api/cameras");
      state.cameras = data.cameras || [];
      state.storage = data.storage || null;
      state.settings = data.settings || null;
      renderCameras();
      renderStorageHud();
    } catch {
      systemSummary.textContent = "LINK LOST // RECONNECTING TO LOCALHOST...";
    }
  }

  async function fetchRecordings() {
    const params = new URLSearchParams();
    if (state.filters.cameraId) params.set("camera_id", state.filters.cameraId);
    if (state.filters.date) params.set("date", state.filters.date);
    if (state.filters.starredOnly) params.set("starred_only", "true");
    try {
      const data = await apiJson(`/api/recordings?${params.toString()}`);
      state.recordings = data.recordings || [];
      state.dates = data.dates || [];
      state.storage = data.storage || state.storage;
      renderStorageHud();
      renderRecordingsList();
    } catch (err) {
      showToast(err.message || "Failed loading archive");
    }
  }

  // Boot
  fetchCameras();
  window.setInterval(fetchCameras, 2000);
})();
