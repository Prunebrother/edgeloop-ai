import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
    BUTTPLUG_MESSAGE_VERSION,
    buildRequestServerInfo,
    buildPing,
    buildScalarCmd,
    buildLinearCmd,
    buildRotateCmd,
    buildStopAllDevices,
    buildStopDeviceCmd,
    buildSensorReadCmd,
    encodeFrame,
    decodeFrame,
    classifyMessage,
    parseServerInfo,
    pingIntervalMs,
    describeError,
    parseDevice,
    deviceSignature,
    defaultRoleFor,
    isScalarActuator
} from './buttplug-protocol.js';

describe('builders', () => {
    it('produces the v3 handshake', () => {
        assert.deepEqual(buildRequestServerInfo(1), {
            RequestServerInfo: { Id: 1, ClientName: 'EdgeLoop', MessageVersion: BUTTPLUG_MESSAGE_VERSION }
        });
        assert.equal(BUTTPLUG_MESSAGE_VERSION, 3);
        assert.deepEqual(buildPing(7), { Ping: { Id: 7 } });
    });
    it('clamps command values into the spec ranges', () => {
        assert.deepEqual(buildScalarCmd(2, 3, [{ index: 0, scalar: 1.7, actuatorType: 'Vibrate' }]), {
            ScalarCmd: { Id: 2, DeviceIndex: 3, Scalars: [{ Index: 0, Scalar: 1, ActuatorType: 'Vibrate' }] }
        });
        assert.deepEqual(buildLinearCmd(4, 1, [{ index: 0, position: -0.3, durationMs: 180.4 }]), {
            LinearCmd: { Id: 4, DeviceIndex: 1, Vectors: [{ Index: 0, Duration: 180, Position: 0 }] }
        });
        assert.deepEqual(buildRotateCmd(5, 1, [{ index: 0, speed: 0.5, clockwise: false }]), {
            RotateCmd: { Id: 5, DeviceIndex: 1, Rotations: [{ Index: 0, Speed: 0.5, Clockwise: false }] }
        });
        assert.deepEqual(buildStopAllDevices(6), { StopAllDevices: { Id: 6 } });
        assert.deepEqual(buildStopDeviceCmd(7, 2), { StopDeviceCmd: { Id: 7, DeviceIndex: 2 } });
        assert.deepEqual(buildSensorReadCmd(8, 2, 1), {
            SensorReadCmd: { Id: 8, DeviceIndex: 2, SensorIndex: 1, SensorType: 'Battery' }
        });
    });
    it('encodes every frame as a JSON array', () => {
        assert.equal(encodeFrame(buildPing(1)), '[{"Ping":{"Id":1}}]');
        assert.equal(encodeFrame([buildPing(1), buildPing(2)]), '[{"Ping":{"Id":1}},{"Ping":{"Id":2}}]');
    });
});

describe('decodeFrame / classifyMessage', () => {
    it('decodes arrays and tolerates garbage', () => {
        assert.deepEqual(decodeFrame('[{"Ok":{"Id":1}}]'), [{ Ok: { Id: 1 } }]);
        assert.deepEqual(decodeFrame('{"Ok":{"Id":1}}'), [{ Ok: { Id: 1 } }]);
        assert.deepEqual(decodeFrame('not json'), []);
        assert.deepEqual(decodeFrame('[1, null, "x"]'), []);
    });
    it('classifies by the single key and extracts the Id', () => {
        assert.deepEqual(classifyMessage({ Ok: { Id: 12 } }), { type: 'Ok', id: 12, body: { Id: 12 } });
        assert.equal(classifyMessage({ DeviceAdded: { DeviceIndex: 0 } }).id, 0);
        assert.equal(classifyMessage({ A: {}, B: {} }).type, 'unknown');
        assert.equal(classifyMessage(null).type, 'unknown');
    });
});

describe('handshake parsing', () => {
    it('reads ServerInfo', () => {
        assert.deepEqual(parseServerInfo({ Id: 1, ServerName: 'Intiface Central', MessageVersion: 3, MaxPingTime: 1000 }), {
            serverName: 'Intiface Central', messageVersion: 3, maxPingTime: 1000
        });
        assert.deepEqual(parseServerInfo({ Id: 1, MessageVersion: '3', MaxPingTime: 0 }), {
            serverName: 'Intiface', messageVersion: 3, maxPingTime: 0
        });
        assert.equal(parseServerInfo(null), null);
    });
    it('pings at half the server limit, or not at all', () => {
        assert.equal(pingIntervalMs(0), 0);
        assert.equal(pingIntervalMs(-5), 0);
        assert.equal(pingIntervalMs(1000), 500);
        assert.equal(pingIntervalMs(150), 100);
        assert.equal(pingIntervalMs('abc'), 0);
    });
});

describe('error classification', () => {
    it('maps codes to kinds and flags fatal ones', () => {
        assert.deepEqual(describeError({ Id: 3, ErrorMessage: 'bad', ErrorCode: 1 }), {
            code: 1, kind: 'handshake', message: 'bad', fatal: true, unsolicited: false
        });
        assert.equal(describeError({ Id: 0, ErrorMessage: 'ping', ErrorCode: 2 }).unsolicited, true);
        assert.equal(describeError({ Id: 0, ErrorMessage: 'ping', ErrorCode: 2 }).fatal, true);
        assert.equal(describeError({ Id: 9, ErrorMessage: 'dev', ErrorCode: 4 }).kind, 'device');
        assert.equal(describeError({ Id: 9, ErrorMessage: 'dev', ErrorCode: 4 }).fatal, false);
        assert.equal(describeError({ Id: 9, ErrorCode: 3 }).message, 'Intiface error (code 3)');
        assert.equal(describeError({}).kind, 'unknown');
    });
});

describe('parseDevice', () => {
    const osr2 = {
        DeviceIndex: 2,
        DeviceName: 'TCode v0.3 (Single Linear Axis)',
        DeviceMessages: {
            LinearCmd: [{ StepCount: 1000, FeatureDescriptor: 'L0', ActuatorType: 'Position' }],
            StopDeviceCmd: {}
        }
    };
    const lovense = {
        DeviceIndex: 0,
        DeviceName: 'Lovense Edge',
        DeviceDisplayName: 'My Edge',
        DeviceMessageTimingGap: 100,
        DeviceMessages: {
            ScalarCmd: [
                { StepCount: 20, FeatureDescriptor: 'Vibrator 1', ActuatorType: 'Vibrate' },
                { StepCount: 20, FeatureDescriptor: 'Vibrator 2', ActuatorType: 'Vibrate' }
            ],
            SensorReadCmd: [
                { SensorType: 'RSSI', SensorRange: [[-100, 0]], FeatureDescriptor: 'RSSI' },
                { SensorType: 'Battery', SensorRange: [[0, 100]], FeatureDescriptor: 'Battery' }
            ],
            StopDeviceCmd: {}
        }
    };

    it('uses the array position as the index when attributes carry none', () => {
        const parsed = parseDevice(lovense);
        assert.deepEqual(parsed.scalars.map((s) => s.index), [0, 1]);
        assert.equal(parsed.scalars[1].descriptor, 'Vibrator 2');
        assert.equal(parsed.scalars[1].stepCount, 20);
        assert.equal(parsed.displayName, 'My Edge');
        assert.equal(parsed.timingGapMs, 100);
        assert.equal(parsed.canStop, true);
    });
    it('finds the Battery sensor index from the sensor list', () => {
        assert.equal(parseDevice(lovense).batterySensorIndex, 1);
        assert.equal(parseDevice(osr2).batterySensorIndex, null);
    });
    it('exposes an OSR2 as one linear actuator', () => {
        const parsed = parseDevice(osr2);
        assert.equal(parsed.linears.length, 1);
        assert.equal(parsed.linears[0].stepCount, 1000);
        assert.equal(parsed.scalars.length, 0);
    });
    it('tolerates the v2 object form and rejects garbage', () => {
        const parsed = parseDevice({ DeviceIndex: 1, DeviceName: 'Old', DeviceMessages: { VibrateCmd: { FeatureCount: 2 }, ScalarCmd: { FeatureCount: 2, ActuatorType: 'Vibrate' } } });
        assert.deepEqual(parsed.scalars.map((s) => s.index), [0, 1]);
        assert.equal(parseDevice(null), null);
        assert.equal(parseDevice({ DeviceName: 'no index' }), null);
        assert.equal(parseDevice({ DeviceIndex: 3 }).name, 'Device 3');
    });
    it('builds a signature from the name and actuator layout', () => {
        assert.equal(deviceSignature(parseDevice(lovense)), 'Lovense Edge|S:Vibrate,Vibrate|L:|R:');
        assert.equal(deviceSignature(parseDevice(osr2)), 'TCode v0.3 (Single Linear Axis)|S:|L:Position|R:');
    });
    it('defaults roles sensibly', () => {
        const edge = parseDevice(lovense);
        assert.equal(defaultRoleFor(edge, 'scalar', 0), 'secondary');
        const stroker = parseDevice(osr2);
        assert.equal(defaultRoleFor(stroker, 'linear', 0), 'primary');
        assert.equal(defaultRoleFor(stroker, 'linear', 1), 'secondary');
        const vibe = parseDevice({ DeviceIndex: 5, DeviceName: 'Wand', DeviceMessages: { ScalarCmd: [{ ActuatorType: 'Vibrate' }] } });
        assert.equal(defaultRoleFor(vibe, 'scalar', 0), 'primary');
        assert.equal(isScalarActuator('Oscillate'), true);
        assert.equal(isScalarActuator('Rotate'), false);
    });
});
