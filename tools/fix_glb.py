# -*- coding: utf-8 -*-
"""GLB 修复器：合并内容相同的重复 skin（Quaternius 多网格单骨架结构），
使 panda3d gltf 转换器不再因 characters[skinid] KeyError 而加载失败。"""
import json, struct, sys


def load(path):
    data = open(path, 'rb').read()
    magic, ver, total = struct.unpack('<III', data[:12])
    assert magic == 0x46546C67, 'not glb'
    l, t = struct.unpack('<II', data[12:20])
    g = json.loads(data[20:20 + l])
    off = 20 + l + ((4 - l % 4) % 4)
    if off + 8 <= len(data):
        bl, bt = struct.unpack('<II', data[off:off + 8])
        bin_data = data[off + 8:off + 8 + bl]
    else:
        bl, bin_data = 0, b''
    return g, bin_data


def save(path, g, bin_data):
    js = json.dumps(g, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    pad = (4 - len(js) % 4) % 4
    js += b' ' * pad
    bin_pad = (4 - len(bin_data) % 4) % 4
    body = struct.pack('<II', len(js), 0x4E4F534A) + js
    if bin_data:
        body += struct.pack('<II', len(bin_data), 0x004E4942) + bin_data + b'\x00' * bin_pad
    total = 12 + len(body)
    out = struct.pack('<III', 0x46546C67, 2, total) + body
    open(path, 'wb').write(out)
    return total


def merge_skins(g, bin_data):
    accs, bvs = g.get('accessors'), g.get('bufferViews', [])

    def ibm_bytes(s):
        ai = s.get('inverseBindMatrices')
        if ai is None or not accs:
            return b''
        a = accs[ai]
        bv = bvs[a['bufferView']]
        off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
        return bin_data[off:off + 16 * a['count']]

    skins = g.get('skins', [])
    if len(skins) < 2:
        return 0
    canon = {}          # (joints, ibm) -> new index
    keep = []
    for s in skins:
        key = (tuple(s['joints']), ibm_bytes(s))
        if key not in canon:
            canon[key] = len(keep)
            keep.append(s)
    if len(keep) == len(skins):
        return 0        # 无重复，不动
    remap = {}
    for i, s in enumerate(skins):
        remap[i] = canon[(tuple(s['joints']), ibm_bytes(s))]
    for n in g['nodes']:
        if 'skin' in n:
            n['skin'] = remap[n['skin']]
    g['skins'] = keep
    return len(skins) - len(keep)


if __name__ == '__main__':
    for path in sys.argv[1:]:
        g, bin_data = load(path)
        merged = merge_skins(g, bin_data)
        if merged:
            size = save(path, g, bin_data)
            print('%s: merged %d duplicate skins, new size %d' % (path, merged, size))
        else:
            print('%s: no duplicate skins' % path)
