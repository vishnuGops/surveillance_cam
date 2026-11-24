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
  const focusStrip = document.getElementById("focus-strip");
  const camerasEmpty = document.getElementById("cameras-empty");
  const cameraToolbarHint = document.getElementById("camera-toolbar-hint");
  const btnLayoutGrid = document.getElementById("btn-layout-grid");
  const btnLayoutFocus = document.getElementById("btn-layout-focus");

  const recordingPlayer = document.getElementById("recording-player");
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
    toastEl.textContent = message;
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

  // Pause live MJPEG streams when viewing Recordings tab to free browser bandwidth
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

  // ---------------- LAYOUT MODE ----------------
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
  }

  function updateFocusClasses() {
    cameraWall.querySelectorAll(".cam-card").forEach((card) => {
      card.classList.toggle(
        "is-focused",
        card.dataset.camId === state.focusedCameraId
      );
    });
    renderFocusStrip();
  }

  function renderFocusStrip() {
    const showStrip = state.layout === "focus" && state.cameras.length > 1;
    focusStrip.hidden = !showStrip;
    if (!showStrip) return;

    focusStrip.innerHTML = "";
    state.cameras.forEach((cam) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip-btn";
      if (cam.id === state.focusedCameraId) {
        btn.classList.add("is-active");
      }
      btn.textContent = `${cam.online ? "● " : "○ "}${cam.name}`;
      btn.addEventListener("click", () => setLayout("focus", cam.id));
      focusStrip.appendChild(btn);
    });
  }

  btnLayoutGrid.addEventListener("click", () => setLayout("grid"));
  btnLayoutFocus.addEventListener("click", () => setLayout("focus"));

  // ---------------- CAMERA WALL RENDERING ----------------
  function createCameraCard(cam) {
    const card = document.createElement("article");
    card.className = "cam-card";
    card.dataset.camId = cam.id;

    card.innerHTML = `
      <div class="cam-stage">
        <img
          class="cam-stream-img"
          alt=""
          width="1280"
          height="720"
          decoding="async"
        />
        <div class="cam-hud-top">
          <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
            <span class="hud-pill">
              <span class="hud-dot" data-field="dot"></span>
              <span data-field="hud-status">Connecting</span>
            </span>
            <span class="hud-pill hud-rec" data-field="rec-pill" hidden>
              <span class="rec-pulse" aria-hidden="true"></span>
              <span data-field="rec-timer">REC 00:00 / 05:00</span>
            </span>
          </div>
          <span class="hud-pill" data-field="hud-metrics">--</span>
        </div>
        <div class="cam-overlay-msg" data-field="overlay" hidden>Connecting...</div>
        <div class="cam-loop-progress" aria-hidden="true">
          <div class="cam-loop-fill" data-field="loop-fill"></div>
        </div>
      </div>
      <div class="cam-footer">
        <div class="cam-meta">
          <div class="cam-name-row">
            <h2 class="cam-name" data-field="name"></h2>
          </div>
          <span class="cam-sub" data-field="sub"></span>
        </div>
        <div class="cam-actions">
          <button type="button" class="btn btn-sm" data-action="record">Record</button>
          <button type="button" class="btn btn-sm" data-action="snapshot">Snapshot</button>
          <button type="button" class="btn btn-sm" data-action="timestamp">TS</button>
          <button type="button" class="btn btn-sm" data-action="rename">Rename</button>
          <button type="button" class="btn btn-sm" data-action="focus">Focus</button>
          <button type="button" class="btn btn-sm" data-action="fullscreen">Full</button>
        </div>
      </div>
    `;

    card.querySelector('[data-action="record"]').addEventListener("click", async () => {
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
            ? `Recording started on ${current.name}`
            : `Recording paused on ${current.name} (loop saved)`
        );
        await fetchCameras();
      } catch (err) {
        showToast(err.message);
      }
    });

    card.querySelector('[data-action="snapshot"]').addEventListener("click", async () => {
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
        a.download = `${cam.id}_${stamp}.jpg`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        showToast(`Snapshot saved (${current ? current.name : cam.id})`);
      } catch (err) {
        showToast(err.message || "Failed to capture snapshot");
      }
    });

    card.querySelector('[data-action="timestamp"]').addEventListener("click", async () => {
      const current = state.cameras.find((c) => c.id === cam.id);
      if (!current) return;
      try {
        await apiJson(`/api/cameras/${encodeURIComponent(cam.id)}`, {
          method: "PATCH",
          body: JSON.stringify({ show_timestamp: !current.show_timestamp }),
        });
        await fetchCameras();
      } catch (err) {
        showToast(err.message);
      }
    });

    card.querySelector('[data-action="rename"]').addEventListener("click", () => {
      const current = state.cameras.find((c) => c.id === cam.id);
      state.renamingCameraId = cam.id;
      inputCameraName.value = current ? current.name : cam.name;
      dialogRename.showModal();
      inputCameraName.select();
    });

    card.querySelector('[data-action="focus"]').addEventListener("click", () => {
      if (state.layout === "focus" && state.focusedCameraId === cam.id) {
        setLayout("grid");
      } else {
        setLayout("focus", cam.id);
      }
    });

    card.querySelector('[data-action="fullscreen"]').addEventListener("click", async () => {
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
    const dot = card.querySelector('[data-field="dot"]');
    const hudStatus = card.querySelector('[data-field="hud-status"]');
    const recPill = card.querySelector('[data-field="rec-pill"]');
    const recTimer = card.querySelector('[data-field="rec-timer"]');
    const hudMetrics = card.querySelector('[data-field="hud-metrics"]');
    const overlay = card.querySelector('[data-field="overlay"]');
    const loopFill = card.querySelector('[data-field="loop-fill"]');
    const nameEl = card.querySelector('[data-field="name"]');
    const imgEl = card.querySelector("img.cam-stream-img");
    const subEl = card.querySelector('[data-field="sub"]');

    const btnRec = card.querySelector('[data-action="record"]');
    const btnTs = card.querySelector('[data-action="timestamp"]');
    const btnFocus = card.querySelector('[data-action="focus"]');

    nameEl.textContent = cam.name;
    if (imgEl) imgEl.alt = `Live feed from ${cam.name}`;
    const resText =
      cam.resolution?.width && cam.resolution?.height
        ? `${cam.resolution.width}×${cam.resolution.height}`
        : "--";
    const fpsText = `${Number(cam.fps || 0).toFixed(1)} FPS`;
    hudMetrics.textContent = `${resText} · ${fpsText}`;
    subEl.textContent = `USB #${cam.index} · ${cam.active_viewers} viewer${
      cam.active_viewers === 1 ? "" : "s"
    } · ${cam.recording.segments_completed} loop${
      cam.recording.segments_completed === 1 ? "" : "s"
    } saved`;

    dot.classList.toggle("is-online", Boolean(cam.online));
    dot.classList.toggle("is-offline", !cam.online);
    hudStatus.textContent = cam.online ? "LIVE" : "OFFLINE";

    if (!cam.online) {
      overlay.textContent = cam.error || "Waiting for webcam signal...";
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

    btnRec.textContent = recEnabled ? "● Rec On" : "Rec Off";
    btnRec.classList.toggle("btn-rec-active", recEnabled);

    btnTs.textContent = cam.show_timestamp ? "TS: On" : "TS: Off";
    btnTs.classList.toggle("is-active", Boolean(cam.show_timestamp));

    const isFocused = state.layout === "focus" && state.focusedCameraId === cam.id;
    btnFocus.textContent = isFocused ? "Exit Focus" : "Focus";
  }

  function renderCameras() {
    const cams = state.cameras;
    badgeCameras.textContent = String(cams.length);
    cameraWall.dataset.count = String(cams.length);
    camerasEmpty.hidden = cams.length > 0;

    if (!state.focusedCameraId && cams.length > 0) {
      state.focusedCameraId = cams[0].id;
    }

    // Reconcile existing DOM cards without destroying live MJPEG elements
    const existingIds = new Set();
    cameraWall.querySelectorAll(".cam-card").forEach((card) => {
      const id = card.dataset.camId;
      if (!cams.some((c) => c.id === id)) {
        card.remove();
      } else {
        existingIds.add(id);
      }
    });

    cams.forEach((cam) => {
      let card = cameraWall.querySelector(`.cam-card[data-cam-id="${CSS.escape(cam.id)}"]`);
      if (!card) {
        card = createCameraCard(cam);
        cameraWall.appendChild(card);
      }
      updateCameraCard(card, cam);
    });

    updateFocusClasses();
    syncStreamSources();

    const onlineCount = cams.filter((c) => c.online).length;
    const recCount = cams.filter((c) => c.recording?.active).length;
    systemSummary.textContent = cams.length
      ? `${onlineCount}/${cams.length} Online · ${recCount} Recording`
      : "No USB cameras connected";

    if (state.settings) {
      const mins = Math.round((state.settings.segment_duration_seconds || 300) / 60);
      cameraToolbarHint.textContent = `Continuous ${mins}-min H.264 loops → ${state.settings.data_dir}`;
    }

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

    filterCamera.innerHTML = `<option value="">All Cameras</option>`;
    known.forEach((name, id) => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = name;
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
      storagePillMeta.textContent = `${formatBytes(usedBytes)} (No cap)`;
      storageBarFill.style.setProperty("--usage-pct", "18%");
    }

    modalStoragePath.textContent = st.data_dir || "C:\\SurveillanceData";
    modalRecUsed.textContent = formatBytes(usedBytes);
    modalRecCount.textContent = `${st.recordings_count} (${st.locked_count} ★)`;
    modalDiskFree.textContent = formatBytes(st.disk_free_bytes);
  }

  // ---------------- RECORDINGS TAB ----------------
  function selectClip(clipId) {
    const clip = state.recordings.find((r) => r.id === clipId);
    state.selectedClipId = clip ? clip.id : null;

    clipList.querySelectorAll(".clip-item").forEach((btn) => {
      btn.classList.toggle("is-selected", btn.dataset.clipId === state.selectedClipId);
    });

    if (!clip) {
      recordingPlayer.pause();
      recordingPlayer.removeAttribute("src");
      recordingPlayer.removeAttribute("poster");
      recordingPlayer.load();
      theaterPlaceholder.hidden = false;
      theaterBar.hidden = true;
      return;
    }

    theaterPlaceholder.hidden = true;
    theaterBar.hidden = false;

    if (clip.thumbnail_url) {
      recordingPlayer.poster = clip.thumbnail_url;
    } else {
      recordingPlayer.removeAttribute("poster");
    }

    recordingPlayer.src = clip.video_url;
    recordingPlayer.playbackRate = state.playbackSpeed;
    recordingPlayer.play().catch(() => {
      // Autoplay might be blocked until user interaction; controls are visible.
    });

    updatePlayerHeader(clip);
  }

  function updatePlayerHeader(clip) {
    playerClipTitle.textContent = `${clip.camera_name} — ${formatClipDateTime(
      clip.started_at
    )}`;
    const res = clip.width && clip.height ? `${clip.width}×${clip.height}` : "--";
    playerClipMeta.textContent = `Duration ${formatDuration(
      clip.duration_seconds
    )} · ${formatBytes(clip.size_bytes)} · ${res} · ${clip.filename}`;

    playerLockedBadge.hidden = !clip.locked;
    btnToggleStar.textContent = clip.locked ? "★ Starred" : "☆ Star";
    btnToggleStar.classList.toggle("btn-star-active", Boolean(clip.locked));
    btnToggleStar.setAttribute("aria-pressed", String(Boolean(clip.locked)));

    btnDownloadClip.href = clip.download_url;
    btnDownloadClip.download = `${clip.camera_id}_${clip.date}_${clip.filename}`;

    btnDeleteClip.disabled = Boolean(clip.locked);
    btnDeleteClip.title = clip.locked
      ? "Unstar clip before deleting"
      : "Delete this recording";

    const idx = state.recordings.findIndex((r) => r.id === clip.id);
    btnPrevClip.disabled = idx <= 0;
    btnNextClip.disabled = idx < 0 || idx >= state.recordings.length - 1;
  }

  function renderRecordingsList() {
    const recs = state.recordings;
    const totalBytes = recs.reduce((acc, r) => acc + (r.size_bytes || 0), 0);

    clipCountLabel.textContent = `${recs.length} clip${recs.length === 1 ? "" : "s"}`;
    clipStorageLabel.textContent = formatBytes(totalBytes);
    recordingsEmpty.hidden = recs.length > 0;

    // Update date filter dropdown while preserving current selection
    const currentDate = filterDate.value;
    filterDate.innerHTML = `<option value="">All Dates</option>`;
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
    recs.forEach((clip) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "clip-item";
      btn.dataset.clipId = clip.id;
      if (clip.id === state.selectedClipId) {
        btn.classList.add("is-selected");
      }

      const thumbMarkup = clip.thumbnail_url
        ? `<img src="${clip.thumbnail_url}" alt="" width="112" height="63" loading="lazy" />`
        : "";
      const starTag = clip.locked
        ? `<span class="clip-star-tag" aria-label="Starred">★</span>`
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
      li.appendChild(btn);
      clipList.appendChild(li);
    });

    if (recs.length === 0) {
      selectClip(null);
    } else if (state.selectedClipId) {
      const existing = recs.find((r) => r.id === state.selectedClipId);
      if (existing) {
        updatePlayerHeader(existing);
      } else {
        selectClip(recs[0].id);
      }
    } else if (state.activeTab === "recordings") {
      selectClip(recs[0].id);
    }
  }

  // Player controls
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
          ? "Clip starred & protected from auto-cleanup"
          : "Clip protection removed"
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
      showToast("Recording deleted");
      await fetchRecordings();
      await fetchCameras();
    } catch (err) {
      showToast(err.message);
    }
  });

  // Filters
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
    showToast("Recordings refreshed");
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
      showToast("Storage & retention settings saved");
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
          ? `Cleanup removed ${n} old clip(s) (${formatBytes(data.cleanup.reclaimed_bytes)})`
          : "Storage is already within your retention limits"
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
      showToast(`Renamed camera to "${newName}"`);
      await fetchCameras();
    } catch (err) {
      showToast(err.message);
    }
  });

  // Scan USB cameras
  btnScanCameras.addEventListener("click", async () => {
    btnScanCameras.disabled = true;
    try {
      const data = await apiJson("/api/cameras/scan", { method: "POST" });
      state.cameras = data.cameras || [];
      renderCameras();
      showToast(`Scan complete — ${state.cameras.length} camera(s) ready`);
    } catch (err) {
      showToast(err.message);
    } finally {
      btnScanCameras.disabled = false;
    }
  });

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
      systemSummary.textContent = "Server disconnected — retrying...";
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
      showToast(err.message || "Failed loading recordings");
    }
  }

  // Boot
  fetchCameras();
  window.setInterval(fetchCameras, 2000);
})();
