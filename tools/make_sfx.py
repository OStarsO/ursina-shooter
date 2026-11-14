# -*- coding: utf-8 -*-
"""生成切换音效 + 加工 CC0 换弹素材。

sfx/switch_gun.wav   切枪：布料摩擦 swish + 两次机械咔嗒（拔枪/上膛）
sfx/switch_knife.wav 切刀：金属鞘声 shing（高频泛音簇 + 快速衰减）
sfx/reload_done.wav  装弹到位：来自 OpenGameArt「Gun Reload Sound Effects」
                     by Brian MacIntosh（CC0），峰值归一化 + 边缘淡入淡出。
"""
import wave
import struct
import math
import random

SR = 44100


def write_wav(path, samples):
    peak = max(1e-9, max(abs(s) for s in samples))
    scale = min(1.0, 0.82 / peak)
    frames = b''.join(struct.pack('<h', int(max(-1, min(1, s * scale)) * 32767))
                      for s in samples)
    w = wave.open(path, 'w')
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(frames)
    w.close()
    print('wrote', path, round(len(samples) / SR, 2), 's')


def env(t, a, r, dur):
    """attack/release 包络"""
    if t < a:
        return t / max(a, 1e-6)
    if t > dur - r:
        return max(0.0, (dur - t) / max(r, 1e-6))
    return 1.0


def make_switch_gun():
    dur = 0.30
    n = int(SR * dur)
    out = [0.0] * n
    # 布料 swish：低通白噪声（一次差分平滑），0 ~ 0.16s
    lp = 0.0
    for i in range(int(SR * 0.17)):
        t = i / SR
        noise = random.uniform(-1, 1)
        lp += 0.22 * (noise - lp)               # 简单一阶低通
        amp = math.sin(math.pi * t / 0.17) ** 2 * 0.9
        out[i] += lp * amp * 0.55
    # 咔嗒 ×2：阻尼正弦 + 噪声瞬态
    for start, freq, amp in ((0.16, 1900, 0.8), (0.235, 2700, 0.7)):
        idx = int(start * SR)
        for j in range(int(SR * 0.05)):
            t = j / SR
            if idx + j >= n:
                break
            decay = math.exp(-t * 90)
            s = (math.sin(2 * math.pi * freq * t)
                 + 0.5 * math.sin(2 * math.pi * freq * 1.7 * t))
            out[idx + j] += s * decay * amp * 0.5 + random.uniform(-1, 1) * decay * 0.12
    write_wav('sfx/switch_gun.wav', out)


def make_switch_knife():
    dur = 0.26
    n = int(SR * dur)
    out = [0.0] * n
    # 起手 whoosh（噪声扫频感）：0 ~ 0.09s
    lp = 0.0
    for i in range(int(SR * 0.09)):
        t = i / SR
        noise = random.uniform(-1, 1)
        lp += 0.3 * (noise - lp)
        out[i] += lp * math.sin(math.pi * t / 0.09) * 0.5
    # 金属 shing：高频泛音簇快衰减（2.4k / 3.7k / 5.2k Hz）
    idx = int(0.055 * SR)
    for j in range(int(SR * 0.20)):
        t = j / SR
        if idx + j >= n:
            break
        decay = math.exp(-t * 26)
        s = (math.sin(2 * math.pi * 2400 * t) * 0.5
             + math.sin(2 * math.pi * 3700 * t) * 0.35
             + math.sin(2 * math.pi * 5200 * t) * 0.3
             + math.sin(2 * math.pi * 7600 * t) * 0.15)
        out[idx + j] += s * decay * 0.42
    write_wav('sfx/switch_knife.wav', out)


def process_reload_done():
    """读入 clipload1（CC0），归一化 + 3ms 边缘淡入淡出 → sfx/reload_done.wav

    源文件 _rl_clipload1.wav 来自 OpenGameArt「Gun Reload Sound Effects」
    （Brian MacIntosh，CC0）：https://opengameart.org/sites/default/files/clipload1.wav
    重新生成前请先下载该文件放到项目根目录。
    """
    import os
    if not os.path.exists('_rl_clipload1.wav'):
        print('跳过 reload_done（缺少 _rl_clipload1.wav，可从上链接重新下载）')
        return
    src = wave.open('_rl_clipload1.wav')
    assert src.getnchannels() == 1 and src.getsampwidth() == 2
    frames = src.readframes(src.getnframes())
    src.close()
    n = len(frames) // 2
    samples = [v / 32768.0 for v in struct.unpack('<%dh' % n, frames)]
    peak = max(1e-9, max(abs(s) for s in samples))
    samples = [s * (0.8 / peak) for s in samples]
    fade = int(SR * 0.003)
    for i in range(fade):
        samples[i] *= i / fade
        samples[-1 - i] *= i / fade
    write_wav('sfx/reload_done.wav', samples)


# ============================ 枪声（每枪独立音色） ============================
# 四把枪 + 刀的击发音效，音色差异刻意拉大：
#   shot_ak.wav     AK-47：连发脆响——高频瞬态裂音 + 220→90Hz 炮体下坠 + 拉栓咔嗒
#   shot_awm.wav    AWM：低频轰鸣——110→45Hz 重炮啁啾 + 远程回声尾
#   shot_usp.wav    USP：清脆短促——420→240Hz "啵" 的一声脆响
#   shot_deagle.wav 沙鹰：厚重炮吼——强瞬态 + 180→70Hz 厚体 + 长尾
#   shot_knife.wav  匕首：挥砍——带通白噪扫掠 + 切割瞬态

def _lowpass(samples, a):
    out, lp = [], 0.0
    for s in samples:
        lp += a * (s - lp)
        out.append(lp)
    return out


def _highpass(samples, a):
    lp = _lowpass(samples, a)
    return [s - l for s, l in zip(samples, lp)]


def _chirp(freq0, freq1, dur, decay, amp, sr=SR):
    """频率下坠的阻尼正弦（枪体的"炮声"成分）。"""
    n = int(sr * dur)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / sr
        f = freq0 + (freq1 - freq0) * (t / dur)
        phase += 2 * math.pi * f / sr
        out.append(math.sin(phase) * math.exp(-t * decay) * amp)
    return out


def _noise_burst(dur, decay, amp, high=False, seed=None):
    if seed is not None:
        random.seed(seed)
    n = int(SR * dur)
    raw = [random.uniform(-1, 1) * math.exp(-i / SR * decay) * amp
           for i in range(n)]
    return _highpass(raw, 0.55) if high else raw


def _mix(base, add, at=0):
    for i, v in enumerate(add):
        j = at + i
        if j >= len(base):
            break
        base[j] += v
    return base


def make_shot_ak():
    dur = 0.24
    out = [0.0] * int(SR * dur)
    _mix(out, _noise_burst(0.05, 200, 1.0, high=True, seed=11))     # 裂音瞬态
    _mix(out, _chirp(220, 90, 0.16, 26, 0.85), at=int(SR * 0.01))   # 炮体下坠
    _mix(out, _noise_burst(0.12, 45, 0.30, seed=12), at=int(SR * 0.02))
    _mix(out, _chirp(2400, 2000, 0.03, 120, 0.35), at=int(SR * 0.10))  # 拉栓
    write_wav('sfx/shot_ak.wav', out)


def make_shot_awm():
    dur = 0.62
    out = [0.0] * int(SR * dur)
    _mix(out, _noise_burst(0.06, 160, 1.0, high=True, seed=21))     # 击发裂音
    _mix(out, _chirp(110, 45, 0.45, 8, 1.0), at=int(SR * 0.01))     # 重炮啁啾
    _mix(out, _noise_burst(0.30, 14, 0.28, seed=22), at=int(SR * 0.03))
    _mix(out, _lowpass(_noise_burst(0.20, 30, 0.45, seed=23), 0.12),
         at=int(SR * 0.14))                                          # 远程回声
    write_wav('sfx/shot_awm.wav', out)


def make_shot_usp():
    dur = 0.11
    out = [0.0] * int(SR * dur)
    _mix(out, _noise_burst(0.02, 300, 0.8, high=True, seed=31))      # 清脆瞬态
    _mix(out, _chirp(420, 240, 0.07, 55, 0.9), at=int(SR * 0.005))   # "啵"体
    write_wav('sfx/shot_usp.wav', out)


def make_shot_deagle():
    dur = 0.34
    out = [0.0] * int(SR * dur)
    _mix(out, _noise_burst(0.04, 150, 1.0, high=True, seed=41))       # 强瞬态
    _mix(out, _chirp(180, 70, 0.26, 13, 1.0), at=int(SR * 0.008))    # 厚体
    _mix(out, _chirp(360, 140, 0.14, 30, 0.4), at=int(SR * 0.01))    # 二次谐波
    _mix(out, _noise_burst(0.22, 16, 0.32, seed=42), at=int(SR * 0.03))
    write_wav('sfx/shot_deagle.wav', out)


def make_shot_knife():
    dur = 0.20
    n = int(SR * dur)
    out = [0.0] * n
    # 挥砍扫掠：带通噪声，幅度先起后落（一阶低通近似带通）
    lp = 0.0
    for i in range(int(SR * 0.13)):
        t = i / SR
        noise = random.uniform(-1, 1)
        lp += 0.5 * (noise - lp)
        band = lp - (lp * 0.6)        # 粗糙带通（低通 - 更深低通）
        amp = math.sin(math.pi * t / 0.13) * 0.7
        out[i] += band * amp
    # 切割瞬态：高频噪声 + 6kHz 金属性微响
    _mix(out, _noise_burst(0.05, 90, 0.7, high=True, seed=51),
         at=int(SR * 0.09))
    _mix(out, _chirp(6200, 5800, 0.06, 70, 0.25), at=int(SR * 0.10))
    write_wav('sfx/shot_knife.wav', out)


if __name__ == '__main__':
    random.seed(7)
    make_switch_gun()
    make_switch_knife()
    process_reload_done()
    make_shot_ak()
    make_shot_awm()
    make_shot_usp()
    make_shot_deagle()
    make_shot_knife()
