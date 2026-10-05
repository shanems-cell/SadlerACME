Ext.ns("SYNO.SDS.SadlerACME");

/*
 * DSM desktop integration.
 *
 * The scheduler-install bridge deliberately uses DSM's already-authenticated
 * desktop session for fixed SadlerACME scheduler operations. The iframe sends
 * only the operation name and administrator password to the same-origin parent;
 * the password is used for SYNO.Core.User.PasswordConfirm and is never posted
 * to SadlerACME's
 * CGI backend.
 */
Ext.define("SYNO.SDS.SadlerACME.Application", {
  extend: "SYNO.SDS.AppInstance",
  appWindowName: "SYNO.SDS.SadlerACME.MainWindow",

  constructor: function () {
    this.callParent(arguments);
  }
});

Ext.define("SYNO.SDS.SadlerACME.MainWindow", {
  extend: "SYNO.SDS.AppWindow",
  constructor: function (config) {
    var self = this;
    var frameId = Ext.id(null, "sadleracme-frame-");

    this._schedulerBridgeHandler = function (event) {
      var data = event.data || {};
      var frame = document.getElementById(frameId);
      if (event.origin !== window.location.origin || !frame || event.source !== frame.contentWindow || data.type !== "sadleracme.scheduler.install") {
        return;
      }
      var requestId = typeof data.requestId === "string" ? data.requestId : "";
      var password = typeof data.password === "string" ? data.password : "";
      var mode = typeof data.mode === "string" ? data.mode : "create";
      var source = event.source;
      var targetOrigin = event.origin;
      var replied = false;
      var ownsRequest = false;
      var token = "";
      data.password = "";
      var names = ["SadlerACME Bootstrap", "SadlerACME Setup"];
      var commands = ["/bin/systemctl start pkg-sadleracme-bootstrap.service", "/bin/systemctl start pkg-sadleracme-setup.service"];
      var allowed = ["create", "set", "delete", "setup", "ensure", "cleanup-setup", "remove-all"];

      function reply(ok, message, extra) {
        if (replied) { return; }
        replied = true;
        password = "";
        token = "";
        if (ownsRequest && self._schedulerBridgeRequest === requestId) { self._schedulerBridgeRequest = ""; }
        var result = {type: "sadleracme.scheduler.result", requestId: requestId, mode: mode, ok: !!ok, message: String(message || "")};
        Object.keys(extra || {}).forEach(function (key) { result[key] = extra[key]; });
        try { source.postMessage(result, targetOrigin); } catch (e) { /* iframe closed */ }
      }
      function problem(message) { reply(false, message + " Check DSM Task Scheduler or the manual recovery instructions."); }
      function payload(value) {
        if (!value || typeof value !== "object" || Array.isArray(value) || value.success === false) { return null; }
        return value.data && typeof value.data === "object" ? value.data : value;
      }
      function request(api, method, version, params, callback) {
        if (replied) { return; }
        try {
          self.sendWebAPI({api: api, method: method, version: version, params: params, scope: self,
            callback: function (ok, response) {
              if (replied) { return; }
              callback(!!ok && !(response && response.success === false), response);
            }});
        } catch (e) { problem("DSM could not complete the scheduler request."); }
      }
      function taskName(task) {
        if (!task || typeof task !== "object" || Array.isArray(task)) { return null; }
        if (typeof task.name === "string" && typeof task.task_name === "string" && task.name !== task.task_name) { return null; }
        return typeof task.task_name === "string" ? task.task_name : (typeof task.name === "string" ? task.name : null);
      }
      function ownerName(owner) {
        if (owner === 0 || owner === "0" || owner === "root") { return "root"; }
        if (owner && typeof owner === "object" && !Array.isArray(owner) && Object.keys(owner).length === 1 && owner["0"] === "root") { return "root"; }
        return typeof owner === "string" ? owner : null;
      }
      function detail(task, name) {
        var body = payload(task);
        if (!body || taskName(body) !== name) { return null; }
        var owner = ownerName(body.owner);
        var command = typeof body.operation === "string" ? body.operation : (body.extra && typeof body.extra.script === "string" ? body.extra.script : null);
        var kind = typeof body.operation_type === "string" ? body.operation_type : body.type;
        var trigger = body.event;
        var enabled = body.enable;
        if (enabled === 0 || enabled === 1) { enabled = enabled === 1; }
        // A translated display action is not a trustworthy script or trigger.
        // Unrecognised event-task detail formats deliberately fail closed.
        if (owner === null || typeof command !== "string" || typeof kind !== "string" || typeof trigger !== "string" || typeof enabled !== "boolean") { return null; }
        return {name: name, owner: owner, operation: command, operation_type: kind, event: trigger, enable: enabled};
      }
      function recognised(task, index) {
        return task && task.name === names[index] && task.owner === "root" && task.operation === commands[index] && task.operation_type === "script" && task.event === "bootup";
      }
      function readTasks(done) {
        var collected = [];
        var expectedTotal = null;
        function page(offset) {
          // TaskScheduler.list is DSM's combined scheduled/event-task inventory.
          // Read every page: absence from a truncated response is not absence.
          request("SYNO.Core.TaskScheduler", "list", 3, {offset: offset, limit: 200, sort_by: "name", sort_direction: "ASC"}, function (ok, response) {
            var body = payload(response);
            if (!ok || !body || !Array.isArray(body.tasks) || typeof body.total !== "number" || body.total < 0 || body.total % 1 !== 0 || body.total > 5000 || (expectedTotal !== null && expectedTotal !== body.total)) {
              problem("DSM's task inventory could not be verified; no task change was made."); return;
            }
            expectedTotal = body.total;
            if (body.tasks.length > 200 || collected.length + body.tasks.length > expectedTotal || (body.tasks.length === 0 && collected.length < expectedTotal)) {
              problem("DSM returned an incomplete task inventory; no task change was made."); return;
            }
            for (var i = 0; i < body.tasks.length; i += 1) {
              if (taskName(body.tasks[i]) === null) { problem("DSM returned an unrecognised task entry; no task change was made."); return; }
              collected.push(body.tasks[i]);
            }
            if (collected.length < expectedTotal) { page(collected.length); return; }
            var found = [[], []];
            collected.forEach(function (task) { var index = names.indexOf(taskName(task)); if (index >= 0) { found[index].push(task); } });
            if (found[0].length > 1 || found[1].length > 1) { problem("More than one task has a SadlerACME task name. Resolve the duplicates before continuing."); return; }
            var result = [null, null];
            function readDetail(index) {
              if (index === 2) { done(result); return; }
              if (!found[index].length) { readDetail(index + 1); return; }
              var task = found[index][0];
              var full = detail(task, names[index]);
              if (full) { result[index] = full; readDetail(index + 1); return; }
              var detailAPI = "SYNO.Core.TaskScheduler";
              var detailVersion = 4;
              var detailParams;
              if (task.type === "event_script") {
                // DSM lists triggered scripts without real_owner or command
                // details. Its event-task getter uses the exact task name.
                detailAPI = "SYNO.Core.EventScheduler";
                detailVersion = 1;
                detailParams = {task_name: names[index]};
              } else {
                if ((typeof task.id !== "number" && typeof task.id !== "string") || typeof task.real_owner !== "string") {
                  problem("DSM did not expose the full SadlerACME task configuration; no task change was made."); return;
                }
                detailParams = {id: task.id, real_owner: task.real_owner};
              }
              request(detailAPI, "get", detailVersion, detailParams, function (detailOK, responseDetail) {
                if (!detailOK) { problem("DSM could not read the configuration of " + names[index] + ". Refresh DSM and retry before changing the task."); return; }
                var value = detail(responseDetail, names[index]);
                if (!value) { problem("DSM returned incomplete or unrecognised configuration for " + names[index] + ". Task ownership, command and trigger must be verified before continuing."); return; }
                result[index] = value;
                readDetail(index + 1);
              });
            }
            readDetail(0);
          });
        }
        page(0);
      }
      function authenticate(done) {
        if (!password) { reply(false, "Confirm the password for the DSM administrator currently signed in to authorise this task change.", {needsPassword: true}); return; }
        var authParams = {password: password};
        password = "";
        request("SYNO.Core.User.PasswordConfirm", "auth", 2, authParams, function (ok, response) {
          authParams.password = "";
          var body = payload(response);
          token = ok && body && typeof body.SynoConfirmPWToken === "string" ? body.SynoConfirmPWToken : "";
          if (body && typeof body === "object") { body.SynoConfirmPWToken = ""; }
          if (!token) { reply(false, "DSM did not return a valid administrator confirmation. Confirm your password again to retry.", {needsPassword: true}); return; }
          done();
        });
      }
      function verifyUnchanged(before, done) {
        readTasks(function (current) {
          if (JSON.stringify(before) !== JSON.stringify(current)) { problem("SadlerACME tasks changed while approval was requested. Check their state and try again."); return; }
          done(current);
        });
      }
      function runTask(index, extra) {
        password = "";
        request("SYNO.Core.EventScheduler", "run", 1, {task_name: names[index]}, function (ok) {
          if (!ok) { reply(false, names[index] + " exists, but DSM did not start it. Run it from DSM Task Scheduler, then retry.", {taskSaved: true, temporary: index === 1}); return; }
          reply(true, names[index] + " started. Waiting for the protected worker to report ready.", extra || {temporary: index === 1, taskSaved: true});
        });
      }
      function saveTask(before, index, method) {
        authenticate(function () {
          verifyUnchanged(before, function () {
            var params = {task_name: names[index], owner: {0: "root"}, event: "bootup", enable: index === 0,
              depend_on_task: "", notify_enable: false, notify_mail: "", notify_if_error: false,
              operation_type: "script", operation: commands[index], SynoConfirmPWToken: token};
            token = "";
            request("SYNO.Core.EventScheduler.Root", method, 1, params, function (ok) {
              params.SynoConfirmPWToken = "";
              if (!ok) { reply(false, "DSM did not save the task. Check its current state and confirm your password again to retry.", {needsPassword: true}); return; }
              readTasks(function (after) {
                if (!recognised(after[index], index) || after[index].enable !== (index === 0)) { problem("DSM accepted the task change, but the resulting configuration could not be verified."); return; }
                runTask(index, {temporary: index === 1, taskSaved: true, created: method === "create"});
              });
            });
          });
        });
      }
      function removeTasks(before, indices) {
        var remaining = indices.filter(function (index) { return !!before[index]; });
        if (!remaining.length) { reply(true, "The selected SadlerACME tasks are already absent.", {tasksAbsent: true}); return; }
        for (var i = 0; i < remaining.length; i += 1) {
          if (!recognised(before[remaining[i]], remaining[i])) { problem("A SadlerACME task name belongs to an unexpected configuration. It was not removed automatically."); return; }
        }
        authenticate(function () {
          verifyUnchanged(before, function () {
            function removeNext(position) {
              if (position === remaining.length) {
                readTasks(function (after) {
                  if (indices.some(function (index) { return after[index] !== null; })) { problem("A selected task still exists after removal. Preparation has not completed."); return; }
                  reply(true, "Selected SadlerACME tasks removed. Continue worker cleanup and wait for its confirmation.", {tasksAbsent: true});
                });
                return;
              }
              var params = {task_name: names[remaining[position]], SynoConfirmPWToken: token};
              request("SYNO.Core.EventScheduler", "delete", 1, params, function (ok) {
                params.SynoConfirmPWToken = "";
                if (!ok) {
                  reply(false, "DSM did not remove every selected task. Some may already be removed. Confirm your password again to continue safely.", {needsPassword: true, partial: position > 0}); return;
                }
                removeNext(position + 1);
              });
            }
            // A token is reused only inside this immediate deletion transaction.
            // DSM may reject reuse; no password is retained to renew approval.
            removeNext(0);
          });
        });
      }
      function legacyChange() {
        // Preserve the DSM-tested manual controls. New guided modes use the
        // stricter discovery path below; older DSM detail schemas must not
        // disable the existing manual create/update/delete recovery controls.
        authenticate(function () {
          var params = mode === "delete" ? {task_name: names[0], SynoConfirmPWToken: token} : {
            task_name: names[0], owner: {0: "root"}, event: "bootup", enable: true,
            depend_on_task: "", notify_enable: false, notify_mail: "", notify_if_error: false,
            operation_type: "script", operation: commands[0], SynoConfirmPWToken: token
          };
          token = "";
          request(mode === "delete" ? "SYNO.Core.EventScheduler" : "SYNO.Core.EventScheduler.Root", mode, 1, params, function (ok) {
            params.SynoConfirmPWToken = "";
            if (!ok) { reply(false, "DSM did not complete the task change. Check its current state, then confirm your password again to retry.", {needsPassword: true}); return; }
            if (mode === "delete") {
              reply(true, "Bootstrap task removed. Wait for protected worker preparation to complete before using Package Center."); return;
            }
            runTask(0, {temporary: false, taskSaved: true});
          });
        });
      }
      if (allowed.indexOf(mode) < 0 || !/^[A-Za-z0-9_-]{1,100}$/.test(requestId)) { password = ""; return; }
      if (self._schedulerBridgeRequest) { reply(false, "Another scheduler operation is still running. Wait for its result before retrying."); return; }
      self._schedulerBridgeRequest = requestId;
      ownsRequest = true;
      if (typeof self.sendWebAPI !== "function") { problem("DSM's desktop WebAPI bridge is unavailable. Reopen SadlerACME from the DSM desktop."); return; }
      if (["create", "set", "delete"].indexOf(mode) >= 0) { legacyChange(); return; }
      readTasks(function (tasks) {
        if (mode === "delete" || mode === "remove-all" || mode === "cleanup-setup") {
          removeTasks(tasks, mode === "delete" ? [0] : (mode === "cleanup-setup" ? [1] : [0, 1])); return;
        }
        if (mode === "setup") {
          if (tasks[0]) {
            if (!recognised(tasks[0], 0) || !tasks[0].enable) { problem("The existing bootstrap task is disabled or needs correction. Correct it in Automation before guided setup."); return; }
            runTask(0, {temporary: false, reused: true}); return;
          }
          if (tasks[1]) {
            if (!recognised(tasks[1], 1) || tasks[1].enable) { problem("The temporary setup task does not match the expected disabled task. It was not run."); return; }
            runTask(1, {temporary: true, reused: true}); return;
          }
          saveTask(tasks, 1, "create"); return;
        }
        if (tasks[0] && recognised(tasks[0], 0) && tasks[0].enable) { runTask(0, {temporary: false, reused: true}); return; }
        if (mode === "set" && !tasks[0]) { problem("The bootstrap task is missing. Choose Create or use guided setup."); return; }
        if (mode === "create" && tasks[0]) { problem("A bootstrap task already exists. Choose Update instead of creating another."); return; }
        saveTask(tasks, 0, tasks[0] ? "set" : "create");
      });
    };

    window.addEventListener("message", this._schedulerBridgeHandler, false);

    // DSM's authentication helper needs the desktop session's SynoToken when
    // CSRF protection is enabled. Plain iframe URLs do not inherit it.
    var appUrl = "/webman/3rdparty/sadleracme/index.cgi";
    if (typeof Ext.urlAppend === "function") {
      appUrl = Ext.urlAppend(appUrl, "");
    }
    var sessionToken = SYNO.SDS.Session && SYNO.SDS.Session.SynoToken;
    if (typeof sessionToken === "string" && sessionToken && !/[?&]SynoToken=/.test(appUrl)) {
      appUrl += (appUrl.indexOf("?") < 0 ? "?" : "&") + "SynoToken=" + encodeURIComponent(sessionToken);
    }

    // Window size belongs in the constructor config passed to AppWindow.
    // Prototype defaults alone did not reach DSM's first-launch sizing path.
    // These are desktop CSS pixels, not the iframe's content dimensions.
    var preferredWidth = 1320;
    var preferredHeight = 820;
    var preferredMinWidth = 900;
    var preferredMinHeight = 620;
    var doc = document.documentElement || {};
    function positiveDimension(value, fallback) {
      return typeof value === "number" && isFinite(value) && value > 0 ? value : fallback;
    }
    // Leave room for DSM desktop chrome on smaller screens. When a viewport
    // is unavailable (for example during early initialisation), use defaults.
    var viewportWidth = positiveDimension(window.innerWidth,
      positiveDimension(doc.clientWidth, preferredWidth + 32));
    var viewportHeight = positiveDimension(window.innerHeight,
      positiveDimension(doc.clientHeight, preferredHeight + 64));
    var availableWidth = Math.max(1, Math.floor(viewportWidth - 32));
    var availableHeight = Math.max(1, Math.floor(viewportHeight - 64));
    var minWidth = Math.min(preferredMinWidth, availableWidth);
    var minHeight = Math.min(preferredMinHeight, availableHeight);
    var defaultWidth = Math.min(preferredWidth, availableWidth);
    var defaultHeight = Math.min(preferredHeight, availableHeight);

    var windowConfig = Ext.apply({
      width: defaultWidth,
      height: defaultHeight,
      minWidth: minWidth,
      minHeight: minHeight,
      resizable: true,
      maximizable: true,
      minimizable: true,
      title: "SadlerACME",
      layout: "fit",
      border: false,
      items: [{
        xtype: "box",
        autoEl: {
          tag: "iframe",
          id: frameId,
          src: appUrl,
          frameborder: "0",
          style: "width:100%;height:100%;border:0;display:block;background:#171a1d;"
        }
      }]
    }, config || {});

    // Keep usable caller-supplied/saved dimensions and all DSM metadata.
    // Bound invalid/tiny sizes before construction, not in onOpen/onRequest:
    // reopening or receiving a request must not undo a user's resize.
    windowConfig.minWidth = minWidth;
    windowConfig.minHeight = minHeight;
    windowConfig.width = Math.min(availableWidth, Math.max(minWidth,
      positiveDimension(windowConfig.width, defaultWidth)));
    windowConfig.height = Math.min(availableHeight, Math.max(minHeight,
      positiveDimension(windowConfig.height, defaultHeight)));

    // Do not seed x/y: DSM restores pageX/pageY from restoreSizePos. Supplying
    // a competing local position can override that geometry during rendering.
    // Invalid/partial caller coordinates are not a usable position.
    function coordinate(value) {
      return typeof value === "number" && isFinite(value);
    }
    function pair(a, b) {
      return coordinate(a) && coordinate(b) ? [a, b] : null;
    }
    if (!pair(windowConfig.pageX, windowConfig.pageY)) {
      delete windowConfig.pageX;
      delete windowConfig.pageY;
    }
    if (!pair(windowConfig.x, windowConfig.y)) {
      delete windowConfig.x;
      delete windowConfig.y;
    }
    // This is a per-window snapshot, not another preference store. The native
    // pre-render hook below replaces it with DSM's final restored config.
    this._sadlerInitialGeometry = {
      page: pair(windowConfig.pageX, windowConfig.pageY),
      local: pair(windowConfig.x, windowConfig.y)
    };
    this.callParent([windowConfig]);

    var initialBounds = {left: 16, top: 40, width: availableWidth, height: availableHeight};
    function boundedPosition(bounds, width, height, x, y) {
      return [Math.max(bounds.left, Math.min(bounds.left + Math.max(0, bounds.width - width), x)),
        Math.max(bounds.top, Math.min(bounds.top + Math.max(0, bounds.height - height), y))];
    }
    function readPosition(local) {
      try {
        var value = typeof self.getPosition === "function" ? self.getPosition(local) : null;
        return value ? pair(value[0], value[1]) : null;
      } catch (e) { return null; }
    }
    function placeFirstWindow() {
      if (self._initialPlacementDone) return;
      self._initialPlacementDone = true;
      // Standalone and maximised/minimised windows belong to DSM's own layout.
      if (self.isStandaloneMainWindow && self.isStandaloneMainWindow()) return;
      if (self.maximized || self.minimized || (typeof self.setPagePosition !== "function" && typeof self.setPosition !== "function")) return;
      var bounds = initialBounds;
      try {
        var container = self.container;
        var dom = container && (container.dom || container);
        if (dom && dom !== document.body && dom !== document.documentElement && typeof dom.getBoundingClientRect === "function") {
          var rect = dom.getBoundingClientRect();
          var left = Math.max(8, rect.left + 8), top = Math.max(8, rect.top + 8);
          var right = Math.min(viewportWidth - 8, rect.right - 8);
          var bottom = Math.min(viewportHeight - 8, rect.bottom - 8);
          if (right - left > 240 && bottom - top > 180) bounds = {left: left, top: top, width: right-left, height: bottom-top};
        }
      } catch (e) { /* Conservative viewport allowance remains available. */ }
      var geometry = self._sadlerInitialGeometry || {};
      var current = readPosition(false);
      var local = readPosition(true);
      var offsetX = current && local ? current[0] - local[0] : 0;
      var offsetY = current && local ? current[1] - local[1] : 0;
      var restored = geometry.page || (geometry.local &&
        [geometry.local[0] + offsetX, geometry.local[1] + offsetY]);
      var size = typeof self.getSize === "function" ? self.getSize() : windowConfig;
      var width = positiveDimension(size.width, windowConfig.width);
      var height = positiveDimension(size.height, windowConfig.height);
      var shrunk = false;
      if ((width > bounds.width || height > bounds.height) && typeof self.setSize === "function") {
        self.minWidth = Math.min(minWidth, bounds.width);
        self.minHeight = Math.min(minHeight, bounds.height);
        width = Math.min(width, bounds.width); height = Math.min(height, bounds.height);
        self.setSize(width, height);
        shrunk = true;
      }
      var target = restored || [bounds.left + (bounds.width-width)/2,
        bounds.top + (bounds.height-height)/2];
      var xy = boundedPosition(bounds, width, height, target[0], target[1]);
      // In-bounds native restoration needs NO extra setter or preference write.
      // Only a fresh opening or an out-of-bounds correction needs placement.
      if (restored && !shrunk && Math.abs(xy[0]-target[0]) < 0.5 && Math.abs(xy[1]-target[1]) < 0.5) return;
      if (typeof self.setPagePosition === "function") {
        self.setPagePosition(Math.round(xy[0]), Math.round(xy[1]));
      } else {
        self.setPosition(Math.round(xy[0]-offsetX), Math.round(xy[1]-offsetY));
      }
    }
    if (typeof self.on === "function") self.on("show", placeFirstWindow, self, {single: true});
  },

  overwriteAppWinConfig: function (config) {
    // Native AppWindow calls this after merging restoreSizePos, before rendering.
    // Capture that explicit geometry instead of guessing from post-render moves
    // or consulting Ext.state.Manager (not DSM's restoreSizePos provider).
    var nativeConfig = this.callParent([config]) || config;
    var result = Ext.apply({}, nativeConfig);
    function pair(a, b) {
      return typeof a === "number" && isFinite(a) && typeof b === "number" && isFinite(b) ? [a, b] : null;
    }
    var page = pair(result.pageX, result.pageY);
    var local = pair(result.x, result.y);
    this._sadlerInitialGeometry = {page: page, local: page ? null : local};
    // Use only one coordinate system. A native page pair takes precedence over
    // stale local coordinates that may accompany restored/caller configuration.
    if (page || !local) { delete result.x; delete result.y; }
    if (!page) { delete result.pageX; delete result.pageY; }
    return result;
  },

  onOpen: function (info) {
    this.callParent([info]);
  },

  onRequest: function (info) {
    this.onOpen(info);
  },

  onDestroy: function () {
    if (this._schedulerBridgeHandler) {
      window.removeEventListener("message", this._schedulerBridgeHandler, false);
      this._schedulerBridgeHandler = null;
    }
    this.callParent(arguments);
  }
});
