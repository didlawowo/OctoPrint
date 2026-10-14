/* global OCTOPRINT_VIEWMODELS */
(function (root) {
    "use strict";

    const HOME = "#tab_plugin_atelier";
    const numeric = (value) => typeof value === "number" && Number.isFinite(value);
    const progress = (value) => (numeric(value) ? Math.max(0, Math.min(100, value)) : 0);
    const temperature = (value) =>
        numeric(value)
            ? value.toLocaleString("fr-FR", {maximumFractionDigits: 1}) + " °C"
            : "—";
    const sparkline = (values) => {
        const points = values.filter(numeric).slice(-120);
        if (points.length < 2) return "";
        const low = Math.min(...points) - 2;
        const range = Math.max(4, Math.max(...points) - low + 2);
        return points
            .map(
                (v, i) =>
                    `${((i * 180) / (points.length - 1)).toFixed(1)},${(44 - ((v - low) * 40) / range).toFixed(1)}`
            )
            .join(" ");
    };
    const cameraUrl = (value, base) => {
        if (!value || typeof value !== "string") return "";
        try {
            const url = new URL(value, base);
            // HLS, video files and WebRTC retain the native webcam player.
            if (
                !/^https?:$/.test(url.protocol) ||
                /\.(m3u8|mp4|webm)$/i.test(url.pathname) ||
                /webrtc/i.test(url.pathname)
            )
                return "";
            return url.href;
        } catch (_) {
            return "";
        }
    };
    const appendHistory = (previous, samples) => {
        const result = {...previous};
        for (const sample of Array.isArray(samples) ? samples : []) {
            if (!sample || !numeric(sample.time)) continue;
            for (const key of Object.keys(sample)) {
                if (
                    !/^(tool\d+|bed|chamber)$/.test(key) ||
                    !sample[key] ||
                    !numeric(sample[key].actual)
                )
                    continue;
                const points = (result[key] || []).filter((p) => p.time !== sample.time);
                points.push({time: sample.time, value: sample[key].actual});
                result[key] = points.sort((a, b) => a.time - b.time).slice(-120);
            }
        }
        return result;
    };

    function AtelierViewModel(parameters) {
        const self = this;
        const ko = root.ko;
        const $ = root.jQuery;
        const unwrap = ko.unwrap;
        self.state = parameters[0];
        self.temperatures = parameters[1];
        self.settings = parameters[2];
        self.files = parameters[3];
        self.login = parameters[4];
        self.access = parameters[5];
        self.enabled = ko.observable(
            !new URL(root.location.href).searchParams.has("classic")
        );
        self.section = ko.observable("home");
        self.online = ko.observable(false);
        self.history = ko.observable({});
        self.cameraError = ko.observable(false);
        self.pageVisible = ko.observable(!root.document.hidden);
        const wideQuery = root.matchMedia("(min-width: 1000px)");
        self.wide = ko.observable(wideQuery.matches);
        self.progress = ko.pureComputed(() => progress(unwrap(self.state.progress)));
        self.progressLabel = ko.pureComputed(() => `${Math.round(self.progress())} %`);
        self.hasWebcamPermission = ko.pureComputed(() =>
            self.login.hasPermission(self.access.permissions.WEBCAM)
        );
        self.hasFilesPermission = ko.pureComputed(() =>
            self.login.hasPermission(self.access.permissions.FILES_LIST)
        );
        self.canPrint = ko.pureComputed(
            () =>
                self.online() &&
                !!unwrap(self.state.enablePrint) &&
                !unwrap(self.state.isPaused)
        );
        self.canPause = ko.pureComputed(
            () => self.online() && !!unwrap(self.state.enablePause)
        );
        self.canCancel = ko.pureComputed(
            () => self.online() && !!unwrap(self.state.enableCancel)
        );
        self.statusLabel = ko.pureComputed(() => {
            if (!self.online()) return "Serveur déconnecté";
            if (unwrap(self.state.isError)) return "Erreur imprimante";
            if (unwrap(self.state.isCancelling)) return "Annulation…";
            if (unwrap(self.state.isPausing)) return "Mise en pause…";
            if (unwrap(self.state.isPaused)) return "En pause";
            if (unwrap(self.state.isPrinting)) return "Impression en cours";
            return unwrap(self.state.isOperational)
                ? "Imprimante prête"
                : "Imprimante déconnectée";
        });
        self.connected = ko.pureComputed(
            () => self.online() && !!unwrap(self.state.isOperational)
        );
        self.printerName = ko.pureComputed(() => {
            const profiles = self.settings.printerProfiles;
            const profile = profiles && unwrap(profiles.currentProfileData);
            return profile ? unwrap(profile.name) : "Mon imprimante";
        });
        self.heaters = ko.pureComputed(() => {
            const t = self.temperatures;
            const entries = [...(unwrap(t.tools) || [])];
            if (unwrap(t.hasBed)) entries.push(t.bedTemp);
            if (unwrap(t.hasChamber)) entries.push(t.chamberTemp);
            return entries.filter(Boolean).map((entry) => {
                const key = unwrap(entry.key);
                const points = self.history()[key] || [];
                const known = self.connected() && points.length > 0;
                return {
                    key,
                    name:
                        key === "bed"
                            ? "Plateau"
                            : key === "chamber"
                              ? "Enceinte"
                              : "Buse " + (key || "tool0").replace("tool", "T"),
                    bed: key === "bed",
                    actual: temperature(known ? unwrap(entry.actual) : null),
                    target: temperature(known ? unwrap(entry.target) : null),
                    line: sparkline(known ? points.map((p) => p.value) : [])
                };
            });
        });
        self.recentFiles = ko.pureComputed(() => {
            if (!self.hasFilesPermission()) return [];
            const storage = unwrap(self.files.storageFiles) || {};
            const result = [];
            const visit = (entries) =>
                (entries || []).forEach((entry) => {
                    if (entry.type === "folder") visit(entry.children);
                    else result.push(entry);
                });
            Object.values(storage).forEach((entry) => visit(entry.files));
            return result.sort((a, b) => (b.date || 0) - (a.date || 0)).slice(0, 3);
        });
        self.fileSize = (file) => root.formatSize(file.size || 0);
        const webcamSettings = () => {
            const settings = self.settings.settings;
            return settings && settings.plugins && settings.plugins.classicwebcam;
        };
        self.cameraSource = ko.pureComputed(() => {
            const visible =
                self.section() === "camera" || (self.section() === "home" && self.wide());
            if (
                !self.enabled() ||
                !visible ||
                !self.pageVisible() ||
                !self.online() ||
                !self.hasWebcamPermission() ||
                self.cameraError()
            )
                return "";
            const webcam = webcamSettings();
            return cameraUrl(webcam && unwrap(webcam.stream), root.location.href);
        });
        self.cameraTransform = ko.pureComputed(() => {
            const webcam = webcamSettings();
            if (!webcam) return "none";
            return `rotate(${unwrap(webcam.rotate90) ? 90 : 0}deg) scale(${unwrap(webcam.flipH) ? -1 : 1}, ${unwrap(webcam.flipV) ? -1 : 1})`;
        });
        self.cameraFailed = () => self.cameraError(true);
        self.retryCamera = () => self.cameraError(false);
        self.print = () => {
            if (self.canPrint()) self.state.print();
        };
        self.pause = () => {
            if (self.canPause()) self.state.pause();
        };
        self.cancel = () => {
            if (!self.canCancel()) return;
            // Keep upstream confirmations/hooks; add confirmation if the user disabled it there.
            if (unwrap(self.settings.feature_printCancelConfirmation))
                self.state.cancel();
            else
                root.showConfirmationDialog({
                    message: "Annuler définitivement cette impression ?",
                    cancel: "Continuer l’impression",
                    proceed: "Annuler l’impression",
                    onproceed: () => {
                        if (self.canCancel()) self.state.cancel();
                    }
                });
        };
        self.closeConnection = () => {
            root.document.body.classList.remove("atelier-connection-open");
            if (self.connectionOpener) self.connectionOpener.focus();
        };
        self.openConnection = () => {
            self.connectionOpener = root.document.activeElement;
            root.document.body.classList.add("atelier-connection-open");
            $("#connection").collapse("show");
            root.document.getElementById("atelier-close-connection").focus();
        };
        self.native = (selector, section) => {
            self.closeConnection();
            self.section(section || "advanced");
            root.document.body.classList.toggle(
                "atelier-advanced",
                self.section() === "advanced"
            );
            $("#tabs a")
                .filter((_, a) => a.getAttribute("href") === selector)
                .tab("show");
            root.scrollTo(0, 0);
        };
        self.navigate = (section) => {
            if (section === "control") return self.native("#control", "control");
            if (section === "advanced") return self.native("#temp", "advanced");
            self.closeConnection();
            self.section(section);
            root.document.body.classList.remove("atelier-advanced");
            $("#tabs a[href='" + HOME + "']").tab("show");
            root.scrollTo(0, 0);
        };
        self.classic = () => {
            const url = new URL(root.location.href);
            url.searchParams.set("classic", "1");
            url.hash = "";
            root.location.assign(url.href);
        };
        self.onAfterTabChange = (current) => {
            if (current !== HOME && self.enabled()) {
                self.section(current === "#control" ? "control" : "advanced");
                root.document.body.classList.toggle(
                    "atelier-advanced",
                    current !== "#control"
                );
            }
        };
        const receive = (data, reset) => {
            self.online(true);
            self.history(appendHistory(reset ? {} : self.history(), data && data.temps));
        };
        self.fromCurrentData = (data) => receive(data, false);
        self.fromHistoryData = (data) => receive(data, true);
        self.onServerDisconnect = () => {
            self.online(false);
            self.history({});
        };
        self.onAllBound = () => {
            if (!self.enabled()) {
                root.document.body.classList.add("atelier-classic");
                return;
            }
            let viewport = root.document.querySelector('meta[name="viewport"]');
            if (!viewport) {
                viewport = root.document.createElement("meta");
                viewport.name = "viewport";
                root.document.head.appendChild(viewport);
            }
            viewport.content = "width=device-width, initial-scale=1, viewport-fit=cover";
            root.document.body.classList.add("atelier-ui");
            // Move, never clone/rebind: retain upload, sorting, permissions and plugin hooks.
            const files = root.document.getElementById("files_wrapper");
            const slot = root.document.getElementById("atelier-files-slot");
            if (files && slot) slot.appendChild(files);
            root.document.addEventListener("visibilitychange", () =>
                self.pageVisible(!root.document.hidden)
            );
            wideQuery.addEventListener("change", (event) => self.wide(event.matches));
            root.document.addEventListener("keydown", (event) => {
                if (event.key === "Escape") self.closeConnection();
            });
            self.navigate("home");
        };
    }

    const exports = {
        progress,
        temperature,
        sparkline,
        cameraUrl,
        appendHistory,
        AtelierViewModel
    };
    if (typeof module === "object" && module.exports) module.exports = exports;
    else
        root.jQuery(() => {
            OCTOPRINT_VIEWMODELS.push({
                construct: AtelierViewModel,
                dependencies: [
                    "printerStateViewModel",
                    "temperatureViewModel",
                    "settingsViewModel",
                    "filesViewModel",
                    "loginStateViewModel",
                    "accessViewModel"
                ],
                elements: ["#tab_plugin_atelier", "#atelier-navigation"]
            });
        });
})(typeof window !== "undefined" ? window : globalThis);
