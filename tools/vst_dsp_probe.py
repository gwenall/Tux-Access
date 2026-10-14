"""Independent bounded Linux VST2 DSP experiment; run in a timed subprocess.

ABI facts checked against Carla v2.5.10 primary source (no header copied):
source/includes/vestige/vestige.h and source/utils/CarlaVst2Utils.hpp.
Lifecycle reference: source/discovery/carla-discovery.cpp.
https://github.com/falkTX/Carla/tree/v2.5.10
Does not open an editor, change parameters, persist state, or claim activation.
"""
import argparse
import ctypes as C
import json
import math
import os
from pathlib import Path

I32, IPTR, PTR = C.c_int32, C.c_ssize_t, C.c_void_p
FLOAT_PTR = C.POINTER(C.c_float)


class Effect(C.Structure):
    pass


EFFECT_PTR = C.POINTER(Effect)
DISPATCH = C.CFUNCTYPE(IPTR, EFFECT_PTR, I32, I32, IPTR, PTR, C.c_float)
PROCESS = C.CFUNCTYPE(None, EFFECT_PTR, C.POINTER(FLOAT_PTR), C.POINTER(FLOAT_PTR), I32)
HOST = DISPATCH

# Prefix only: the plug-in allocates this structure; host never allocates it.
Effect._fields_ = [
    ('magic', I32), ('dispatcher', PTR), ('legacy_process', PTR),
    ('set_parameter', PTR), ('get_parameter', PTR),
    ('programs', I32), ('parameters', I32), ('inputs', I32), ('outputs', I32),
    ('flags', I32), ('reserved_a', PTR), ('reserved_b', PTR),
    ('latency', I32), ('reserved_bytes', C.c_ubyte * 8), ('ratio', C.c_float),
    ('instance', PTR), ('host_user', PTR), ('unique_id', I32), ('version', I32),
    ('replacing', PTR),
]


class TimeInfo(C.Structure):
    _fields_ = [(name, C.c_double) for name in
                ('position', 'rate', 'nanoseconds', 'ppq', 'tempo', 'bar', 'cycle_start', 'cycle_end')] + [
                    (name, I32) for name in ('numerator', 'denominator', 'smpte_offset',
                                           'smpte_rate', 'next_clock', 'flags')]


class MidiEvent(C.Structure):
    _fields_ = [(name, I32) for name in ('type', 'size', 'delta', 'flags', 'length', 'offset')] + [
        ('data', C.c_ubyte * 4), ('detune', C.c_int8), ('release_velocity', C.c_ubyte),
        ('reserved_a', C.c_ubyte), ('reserved_b', C.c_ubyte)]


class Events(C.Structure):
    _fields_ = [('count', I32), ('reserved', IPTR), ('events', PTR * 2)]


def run(path, blocks=300, warmup=100, expected_id=None, midi_note=None, allow_silent=False):
    if os.name != 'posix' or C.sizeof(PTR) != 8:
        raise RuntimeError('This experiment requires a 64-bit POSIX host')
    assert Effect.dispatcher.offset == 8 and Effect.replacing.offset == 120
    assert C.sizeof(TimeInfo) == 88
    assert C.sizeof(MidiEvent) == 32 and Events.events.offset == 16
    if not 1 <= warmup < blocks <= 1000:
        raise ValueError('Require 1 <= warmup < blocks <= 1000')
    if midi_note is not None and not 0 <= midi_note <= 127:
        raise ValueError('MIDI note must be 0..127')
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Expected one existing shared-library file')
    rate, frames = 44100, 512
    timeline = TimeInfo()
    timeline.rate, timeline.tempo = rate, 120
    timeline.numerator, timeline.denominator = 4, 4
    timeline.flags = 2 | 512 | 1024 | 2048 | 8192
    directory = C.create_string_buffer(str(path.parent).encode() + b'\0')
    callback_errors = []
    needs_idle = False

    @HOST
    def host(effect, opcode, index, value, pointer, option):
        nonlocal needs_idle
        try:
            if opcode == 1:
                return 2400
            if opcode == 2:
                return expected_id or 0
            if opcode == 7:
                return C.addressof(timeline)
            if opcode == 10:
                return 120 * 10000
            if opcode == 14:
                needs_idle = True
                return 1
            if opcode == 16:
                return rate
            if opcode == 17:
                return frames
            if opcode == 22:
                return 1  # replacing, not accumulation
            if opcode == 23:
                return 4  # offline direct block processing
            if opcode == 24:
                return 1  # automation off
            if opcode in (32, 33) and pointer:
                label = b'IndependentDSPTest\0'
                C.memmove(pointer, label, len(label))
                return 1
            if opcode == 34:
                return 1
            if opcode == 37 and pointer:
                feature_bytes = bytearray()
                for offset in range(128):
                    byte = C.c_ubyte.from_address(pointer + offset).value
                    if not byte:
                        break
                    feature_bytes.append(byte)
                feature = bytes(feature_bytes)
                return 1 if feature == b'sendVstTimeInfo' else 0
            if opcode == 38:
                return 1  # English
            if opcode == 41:
                return C.addressof(directory)
            # No MIDI, editor, dynamic I/O changes, file picker or automation.
            return 0
        except Exception as error:
            callback_errors.append(type(error).__name__)
            return 0

    library = C.CDLL(str(path), mode=os.RTLD_LOCAL | os.RTLD_NOW)
    entry = getattr(library, 'VSTPluginMain', None) or getattr(library, 'main', None)
    if entry is None:
        raise RuntimeError('No VST2 entry point')
    entry.argtypes, entry.restype = [HOST], EFFECT_PTR
    effect = entry(host)
    if not effect or effect.contents.magic != 0x56737450:
        raise RuntimeError('Invalid VST2 effect/magic')
    if not effect.contents.dispatcher:
        raise RuntimeError('Missing VST2 dispatcher')
    dispatcher = DISPATCH(effect.contents.dispatcher)
    opened, active, started = False, False, False
    note_on_sent, note_off_sent = False, False
    def call(opcode, index=0, value=0, pointer=None, option=0.0):
        return dispatcher(effect, opcode, index, value, pointer, option)
    def send_note(on):
        event = MidiEvent()
        event.type, event.size, event.delta = 1, C.sizeof(MidiEvent), 0
        event.data[:] = [0x90 if on else 0x80, midi_note, 100 if on else 0, 0]
        batch = Events()
        batch.count = 1
        batch.events[0] = C.addressof(event)
        # Dispatcher consumes event data synchronously before these locals expire.
        call(25, pointer=C.cast(C.pointer(batch), PTR))
    try:
        call(0)
        opened = True
        info = effect.contents
        if expected_id is not None and info.unique_id != expected_id:
            raise RuntimeError('Unexpected plug-in unique ID')
        if not (0 <= info.inputs <= 16 and 1 <= info.outputs <= 16 and 0 <= info.parameters <= 4096):
            raise RuntimeError('Unsupported or unreasonable effect channel/parameter counts')
        if not info.replacing or not info.flags & 16:
            raise RuntimeError('This harness requires float processReplacing')
        dimensions = (info.inputs, info.outputs)
        process = PROCESS(info.replacing)
        # Use current default preset, without changing parameters or state.
        call(10, option=float(rate))
        call(11, value=frames)
        call(77, value=0)  # 32-bit float processing
        input_buffers = [(C.c_float * frames)() for _ in range(info.inputs)]
        output_buffers = [(C.c_float * frames)() for _ in range(info.outputs)]
        inputs = (FLOAT_PTR * max(1, info.inputs))(*[C.cast(b, FLOAT_PTR) for b in input_buffers])
        outputs = (FLOAT_PTR * info.outputs)(*[C.cast(b, FLOAT_PTR) for b in output_buffers])
        call(12, value=1)
        active = True
        call(71)
        started = True
        sum_input = sum_output = sum_difference = 0.0
        count_input = count_output = count_difference = 0
        peak = 0.0
        for block in range(blocks):
            position = block * frames
            timeline.position = position
            timeline.ppq = position / rate * 2
            timeline.bar = math.floor(timeline.ppq / 4) * 4
            if midi_note is not None and block == warmup:
                send_note(True)
                note_on_sent = True
            if midi_note is not None and block == blocks - 1:
                send_note(False)
                note_off_sent = True
            if (effect.contents.inputs, effect.contents.outputs) != dimensions:
                raise RuntimeError('Plug-in changed I/O dimensions during processing')
            for channel, buffer in enumerate(input_buffers):
                frequency = 440 + channel * 220
                for sample in range(frames):
                    buffer[sample] = .2 * math.sin(2 * math.pi * frequency * (position + sample) / rate)
            for buffer in output_buffers:
                C.memset(C.addressof(buffer), 0, C.sizeof(buffer))
            references = [list(buffer) for buffer in input_buffers]
            process(effect, inputs, outputs, frames)
            if needs_idle:
                call(53)
            for channel, buffer in enumerate(output_buffers):
                for sample, value in enumerate(buffer):
                    if not math.isfinite(value):
                        raise RuntimeError('Non-finite output sample')
                    if block < warmup:
                        continue
                    sum_output += value * value
                    count_output += 1
                    peak = max(peak, abs(value))
                    if channel < len(input_buffers):
                        source = references[channel][sample]
                        sum_difference += (value - source) ** 2
                        count_difference += 1
            if block >= warmup:
                for buffer in references:
                    for value in buffer:
                        sum_input += value * value
                        count_input += 1
            if callback_errors:
                raise RuntimeError('Host callback error')
        output_rms = math.sqrt(sum_output / count_output)
        silent = output_rms <= 1e-8
        if silent and not allow_silent:
            raise RuntimeError('Output remained silent after warmup')
        return {'unique_id': info.unique_id, 'inputs': info.inputs, 'outputs': info.outputs,
                'parameters': info.parameters, 'reported_latency_samples': info.latency,
                'sample_rate': rate, 'block_size': frames, 'blocks': blocks, 'warmup_blocks': warmup,
                'input_rms': math.sqrt(sum_input / count_input) if count_input else None, 'output_rms': output_rms,
                'output_peak': peak, 'output_minus_input_rms': math.sqrt(sum_difference / count_difference) if count_difference else None,
                'finite_nonzero_output': not silent, 'measured_silent': silent,
                'midi_note': midi_note, 'midi_note_on_sent': note_on_sent, 'midi_note_off_sent': note_off_sent,
                'limitation': 'Default-instance DSP observation only; delivered MIDI does not prove it was consumed. Silence is not sound success. Activation, loaded instrument, GUI, and sound quality unconfirmed. Difference is not latency compensated.'}
    finally:
        if midi_note is not None and note_on_sent and not note_off_sent:
            send_note(False)
        if started:
            call(72)
        if active:
            call(12, value=0)
        if opened:
            call(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plugin')
    parser.add_argument('--expected-id', type=int)
    parser.add_argument('--blocks', type=int, default=300)
    parser.add_argument('--warmup', type=int, default=100)
    parser.add_argument('--midi-note', type=int, help='Send channel-1 note-on after warmup and note-off before final block')
    parser.add_argument('--allow-silent', action='store_true', help='Report measured silence without asserting sound success')
    args = parser.parse_args()
    print(json.dumps(run(args.plugin, args.blocks, args.warmup, args.expected_id,
                         args.midi_note, args.allow_silent), indent=2))
