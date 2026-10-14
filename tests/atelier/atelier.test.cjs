const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = path.resolve(__dirname, '../../src/octoprint/plugins/atelier/static/js/atelier.js');
const {progress, temperature, sparkline, cameraUrl, appendHistory, AtelierViewModel} = require(script);

function observable(value) {
    return function (next) { if (arguments.length) value = next; return value; };
}
function model() {
    const calls = [];
    const allowed = new Set(['WEBCAM', 'FILES_LIST']);
    global.ko = {observable, unwrap: (v) => typeof v === 'function' ? v() : v, pureComputed: (fn) => fn};
    global.location = {href: 'http://octopi.local/', assign: (url) => calls.push(url)};
    global.document = {hidden: false};
    global.matchMedia = () => ({matches: true});
    global.formatSize = (n) => String(n);
    global.showConfirmationDialog = (options) => calls.push(options);
    const state = Object.fromEntries(['enablePrint', 'enablePause', 'enableCancel', 'isPaused', 'isOperational', 'isPrinting', 'isError', 'isCancelling', 'isPausing', 'progress'].map((key) => [key, observable(false)]));
    for (const command of ['print', 'pause', 'cancel']) state[command] = () => calls.push(command);
    const tool = {key: observable('tool0'), actual: observable(0), target: observable(0)};
    const temps = {tools: observable([tool]), hasBed: observable(false), hasChamber: observable(false)};
    const settings = {feature_printCancelConfirmation: observable(true), settings: {plugins: {classicwebcam: {stream: observable('/webcam/?action=stream')}}}};
    const files = {storageFiles: observable({})};
    const login = {hasPermission: (p) => allowed.has(p)};
    const access = {permissions: {WEBCAM: 'WEBCAM', FILES_LIST: 'FILES_LIST'}};
    const instance = new AtelierViewModel([state, temps, settings, files, login, access]);
    return {instance, state, temps, settings, files, calls, allowed};
}

test('progress preserves 0, bounds values and rejects malformed telemetry', () => {
    assert.equal(progress(0), 0);
    assert.equal(progress(43.5), 43.5);
    assert.equal(progress(110), 100);
    assert.equal(progress(-1), 0);
    for (const v of [null, undefined, NaN, Infinity, '60']) assert.equal(progress(v), 0);
});
test('temperatures distinguish missing readings and real zero', () => {
    assert.equal(temperature(0), '0 °C');
    assert.equal(temperature(19.34), '19,3 °C');
    for (const v of [null, undefined, NaN, '']) assert.equal(temperature(v), '—');
});
test('sparklines contain no fabricated points, NaN or unbounded coordinates', () => {
    assert.equal(sparkline([]), '');
    assert.equal(sparkline([1]), '');
    assert.equal(sparkline([1, NaN, 1]), '0.0,24.0 180.0,24.0');
    const points = sparkline(Array.from({length: 500}, (_, i) => i)).split(' ');
    assert.equal(points.length, 120);
    for (const point of points) {
        const [x, y] = point.split(',').map(Number);
        assert.ok(x >= 0 && x <= 180 && y >= 0 && y <= 48);
    }
});
test('camera allows relative MJPEG URLs but not script or unsupported video schemes', () => {
    assert.equal(cameraUrl('/webcam/?action=stream', 'http://octopi.local/'), 'http://octopi.local/webcam/?action=stream');
    for (const v of ['javascript:alert(1)', 'data:image/png,x', '/live.m3u8', '/webrtc', '', null]) assert.equal(cameraUrl(v, 'http://octopi.local/'), '');
});
test('history is immutable, deduplicated, chronological and bounded per sensor', () => {
    const old = {tool0: [{time: 2, value: 10}]};
    const result = appendHistory(old, [{time: 2, tool0: {actual: 11}}, {time: 1, tool0: {actual: 0}}, {time: 3, bed: {actual: NaN}, unknown: {actual: 40}}]);
    assert.deepEqual(old.tool0, [{time: 2, value: 10}]);
    assert.deepEqual(result.tool0, [{time: 1, value: 0}, {time: 2, value: 11}]);
    assert.equal(result.unknown, undefined);
    assert.equal(result.bed, undefined);
    assert.equal(appendHistory({}, Array.from({length: 200}, (_, time) => ({time, bed: {actual: time}}))).bed.length, 120);
});
test('all printer actions fail closed before telemetry or after server disconnection', () => {
    const m = model();
    for (const key of ['enablePrint', 'enablePause', 'enableCancel']) m.state[key](true);
    m.instance.print(); m.instance.pause(); m.instance.cancel();
    assert.deepEqual(m.calls, []);
    m.instance.fromCurrentData({temps: []});
    m.instance.print(); m.instance.pause(); m.instance.cancel();
    assert.deepEqual(m.calls, ['print', 'pause', 'cancel']);
    m.instance.onServerDisconnect();
    m.instance.print(); m.instance.pause(); m.instance.cancel();
    assert.equal(m.calls.length, 3);
});
test('native permission flags are retained and paused jobs cannot be restarted from Imprimer', () => {
    const m = model();
    m.instance.fromHistoryData({temps: []});
    m.instance.print(); m.instance.pause(); m.instance.cancel();
    assert.deepEqual(m.calls, []);
    m.state.enablePrint(true);
    m.state.isPaused(true);
    m.instance.print();
    assert.deepEqual(m.calls, []);
});
test('cancel adds a confirmation when upstream confirmation was disabled, with state recheck', () => {
    const m = model();
    m.instance.fromCurrentData({});
    m.state.enableCancel(true);
    m.settings.feature_printCancelConfirmation(false);
    m.instance.cancel();
    assert.equal(typeof m.calls[0].onproceed, 'function');
    m.state.enableCancel(false);
    m.calls[0].onproceed();
    assert.equal(m.calls.length, 1);
});
test('no temperature is shown before a real sample and stale history is cleared', () => {
    const m = model();
    m.state.isOperational(true);
    m.instance.fromCurrentData({temps: []});
    assert.equal(m.instance.heaters()[0].actual, '—');
    m.instance.fromCurrentData({temps: [{time: 1, tool0: {actual: 0}}]});
    assert.equal(m.instance.heaters()[0].actual, '0 °C');
    m.instance.onServerDisconnect();
    assert.equal(m.instance.heaters()[0].actual, '—');
    assert.deepEqual(m.instance.history(), {});
});
test('camera stops when hidden, unauthorized, offline or a different screen is selected', () => {
    const m = model();
    m.instance.fromCurrentData({});
    assert.ok(m.instance.cameraSource());
    m.instance.pageVisible(false); assert.equal(m.instance.cameraSource(), '');
    m.instance.pageVisible(true); m.allowed.delete('WEBCAM'); assert.equal(m.instance.cameraSource(), '');
    m.allowed.add('WEBCAM'); m.instance.section('files'); assert.equal(m.instance.cameraSource(), '');
    m.instance.section('home'); m.instance.wide(false); assert.equal(m.instance.cameraSource(), '');
    m.instance.section('camera'); assert.ok(m.instance.cameraSource());
    m.instance.onServerDisconnect(); assert.equal(m.instance.cameraSource(), '');
});
test('recent files include nested folders but disappear without file-list permission', () => {
    const m = model();
    m.files.storageFiles({local: {files: [{name: 'old', date: 1}, {type: 'folder', children: [{name: '<script>', date: 4}]}]}, printer: {files: [{name: 'sd', date: 3}, {name: 'last', date: 2}]}});
    assert.deepEqual(m.instance.recentFiles().map((f) => f.name), ['<script>', 'sd', 'last']);
    m.allowed.delete('FILES_LIST');
    assert.deepEqual(m.instance.recentFiles(), []);
});
test('classic mode does not enable the new layout', () => {
    model();
    global.location.href = 'http://octopi.local/?classic=1';
    const m = new AtelierViewModel([{}, {}, {}, {}, {hasPermission: () => false}, {permissions: {}}]);
    assert.equal(m.enabled(), false);
});
test('browser registers only the expected bound roots and reuses core viewmodels', () => {
    const registrations = [];
    const context = {window: {jQuery: (fn) => fn()}, OCTOPRINT_VIEWMODELS: registrations};
    vm.runInNewContext(fs.readFileSync(script, 'utf8'), context);
    assert.deepEqual(Array.from(registrations[0].elements), ['#tab_plugin_atelier', '#atelier-navigation']);
    assert.ok(registrations[0].dependencies.includes('printerStateViewModel'));
});
