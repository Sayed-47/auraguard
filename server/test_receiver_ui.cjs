/* Contract tests: real receiver parser snapshots → live dashboard state. */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const path = require('node:path');
const profile = require('../dist/receiver-profile.js');

const script = String.raw`
from datetime import datetime, timedelta, timezone
import json
from server.state import Clock, Monitor, Store
class TestClock(Clock):
    value = 100.0
    def monotonic(self): return self.value
    def now(self): return datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(seconds=self.value)
    def advance(self, seconds): self.value += seconds
clock = TestClock()
monitor = Monitor(Store(':memory:'), protocol='uno-room-v1', clock=clock)
monitor.set_serial(True)
result = {}
def record(name, line=None):
    if line is not None: assert monitor.ingest_line(line), line
    result[name] = monitor.snapshot()
normal = 'status | armed=1 baby=linked lastMsg=0s ago mic=remote cry=0'
record('startup', 'Room unit ready. Cry detection comes from the baby unit (CRY messages).')
clock.advance(2)
record('normal', normal)
record('fall', '!!! FALL ALERT from baby unit !!!')
record('fall_after_status', normal)
record('ack', 'ACKNOWLEDGED (sent ACK to baby unit)')
for _ in range(8):
    clock.advance(2)
    assert monitor.ingest_line(normal)
record('after_mute')
record('cry', 'CRY reported by baby unit')
record('cry_muted', 'ACKNOWLEDGED (sent ACK to baby unit)')
record('cry_ended', 'cry ended')
record('disarmed', 'DISARMED')
record('armed', 'ARMED')
clock.advance(2)
record('restored', normal)
clock.advance(7)
record('link_lost', '!!! LINK LOST - no signal from baby unit !!!')
monitor.set_serial(False)
record('usb_lost')
late = Monitor(Store(':memory:'), protocol='uno-room-v1', clock=clock)
late.set_serial(True)
late.ingest_line(normal)
result['late_attach'] = late.snapshot()
print(json.dumps(result))
`;
const result = spawnSync(process.env.PYTHON || 'python', ['-c',script], {cwd:path.resolve(__dirname,'..'), encoding:'utf8'});
if (result.status !== 0) throw new Error(result.stderr || 'Could not generate receiver snapshots.');
const snapshots = JSON.parse(result.stdout);
const receipt = 10000;
const view = (name, elapsed = 0, connected = true) => profile.view(profile.normalize(snapshots[name]),connected,receipt,receipt + elapsed);

test('unconnected page contains no invented readings', () => {
  const v = profile.view(profile.empty(),false,0,receipt);
  assert.equal(v.status,'waiting'); assert.equal(v.armed,null); assert.equal(v.fall,null); assert.equal(v.age,null);
});
test('startup waits for baby data; fresh status enables monitoring', () => {
  assert.equal(view('startup').status,'pairing'); assert.equal(view('normal').status,'normal'); assert.equal(view('normal').baby,true);
});
test('healthy status cannot clear a latched fall', () => {
  assert.equal(view('fall').status,'fall'); assert.equal(view('fall_after_status').status,'fall');
});
test('physical ACK clears fall and shows the actual mute countdown', () => {
  const v = view('ack'); assert.equal(v.fall,false); assert.equal(v.muted,15); assert.equal(v.status,'muted');
  assert.equal(view('after_mute').status,'normal'); assert.equal(view('after_mute').muted,0);
});
test('historical fall events do not keep the current hero in alert', () => {
  assert(snapshots.after_mute.events.some(e => e.type === 'fall'));
  assert.equal(view('after_mute').status,'normal');
});
test('sound alert remains active through ACK, then follows receiver clear', () => {
  assert.equal(view('cry').status,'cry'); assert.equal(view('cry_muted').cry,true); assert.equal(view('cry_muted').muted,15);
  assert.equal(view('cry_ended').cry,false); assert.equal(view('cry_ended').status,'muted');
});
test('physical ARM state is displayed without claiming new baby traffic', () => {
  assert.equal(view('disarmed').status,'paused'); assert.equal(view('armed').armed,true); assert.equal(view('armed').baby,false);
});
test('link loss and USB loss remove the connected state', () => {
  assert.equal(view('link_lost').status,'offline'); assert.equal(view('link_lost').baby,false);
  assert.equal(view('usb_lost').fresh,false); assert.equal(view('usb_lost').armed,null);
});
test('late attachment preserves unreported fall and mute as unknown', () => {
  const v = view('late_attach'); assert.equal(v.status,'observing'); assert.equal(v.fall,null); assert.equal(v.muted,null);
});
test('stale snapshots stop displaying current alarm flags even without a socket close', () => {
  assert.equal(view('fall',5000).fresh,false); assert.equal(view('fall',5000).fall,null);
  assert.equal(view('fall',6000).status,'disconnected'); assert.equal(view('fall',0,false).fall,null);
});
test('server/browser clock differences do not distort observed mute', () => {
  const raw = profile.normalize(snapshots.ack);
  assert.equal(profile.view(raw,true,1700000000000,1700000002000).muted,13);
});
test('other profiles and non-live streams are rejected', () => {
  assert.throws(() => profile.normalize({...snapshots.normal,mode:'sample'}),/live/);
  assert.throws(() => profile.normalize({...snapshots.normal,protocol:'baby-ble-v5'}),/uno-room-v1/);
});
