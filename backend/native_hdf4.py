"""Read original HDF4 scientific grids without requiring a COG mirror."""
import math
import re

import numpy as np
from pyhdf.SD import SD, SDC

RADIUS = 6371007.181


def _pair(text, name):
    match = re.search(rf'{name}\s*=\s*\(\s*([^,]+),\s*([^\)]+)\)', text)
    if not match:
        raise ValueError(f'HDF-EOS metadata is missing {name}')
    return tuple(float(v) for v in match.groups())


def _degrees(value):
    # HDF-EOS GCTP geographic coordinates use packed DDDMMMSSS.s, not microdegrees.
    if abs(value) <= 360:
        return value
    value_abs = abs(value)
    degree = math.floor(value_abs / 1000000)
    minute = math.floor((value_abs - degree * 1000000) / 1000)
    second = value_abs - degree * 1000000 - minute * 1000
    return math.copysign(degree + minute / 60 + second / 3600, value)


def _grid(metadata, shape, variable):
    groups = re.findall(r'GROUP\s*=\s*(GRID_\d+)\b(.*?)END_GROUP\s*=\s*\1\b', metadata, re.S)
    for _, text in groups or [('', metadata)]:
        if groups and not re.search(r'DataFieldName\s*=\s*"' + re.escape(variable) + r'"', text):
            continue
        xm, ym = re.search(r'\bXDim\s*=\s*(\d+)', text), re.search(r'\bYDim\s*=\s*(\d+)', text)
        if not xm or not ym or tuple(shape[-2:]) != (int(ym[1]), int(xm[1])):
            continue
        ul, lr = _pair(text, 'UpperLeftPointMtrs'), _pair(text, 'LowerRightMtrs')
        projection = re.search(r'\bProjection\s*=\s*"?(\w+)', text)
        projection = projection[1] if projection else ''
        if 'GEO' in projection:
            return 'GEO', tuple(map(_degrees, ul)), tuple(map(_degrees, lr))
        if 'SNSOID' in projection or 'SINUS' in projection:
            return 'SINUSOIDAL', ul, lr
    raise ValueError('No supported geographic/sinusoidal HDF-EOS grid matches the science field')


def convert(path, wants, bbox):
    west, south, east, north = bbox
    source = SD(str(path), SDC.READ)
    output, source_rows = [], 0
    try:
        attrs = source.attributes()
        metadata = '\n'.join(str(attrs[k]) for k in sorted(attrs) if k.lower().startswith('structmetadata'))
        names = [name for name in source.datasets() if any(
            re.sub('[^a-z0-9]', '', word.lower()) in re.sub('[^a-z0-9]', '', name.lower())
            for word in wants if word
        ) and not re.search('quality|reliability|flag|uncertainty', name, re.I)]
        if not names:
            raise ValueError('No HDF4 science variable matches the requested component')
        for name in names:
            dataset = source.select(name)
            try:
                _, rank, shape, _, _ = dataset.info()
                if rank != 2:
                    raise ValueError('HDF4 converter currently requires a two-dimensional science grid')
                projection, ul, lr = _grid(metadata, shape, name)
                height, width = shape
                dx, dy = (lr[0] - ul[0]) / width, (lr[1] - ul[1]) / height
                if not dx or not dy:
                    raise ValueError('Degenerate HDF4 grid bounds')
                points = [(x, y) for x in (west, east) for y in (south, north)]
                if south < 0 < north:
                    points += [(west, 0), (east, 0)]
                if projection == 'SINUSOIDAL':
                    points = [(RADIUS * math.radians(x) * math.cos(math.radians(y)), RADIUS * math.radians(y)) for x, y in points]
                cols = [(x - ul[0]) / dx for x, _ in points]
                rows = [(y - ul[1]) / dy for _, y in points]
                x0, x1 = max(0, math.floor(min(cols)) - 1), min(width, math.ceil(max(cols)) + 1)
                y0, y1 = max(0, math.floor(min(rows)) - 1), min(height, math.ceil(max(rows)) + 1)
                source_rows += height * width
                if x1 <= x0 or y1 <= y0:
                    continue
                if (x1-x0)*(y1-y0) > 2000000:
                    raise ValueError('HDF4 subset exceeds 2 million pixels; choose a smaller area')
                raw = np.asarray(dataset.get(start=(y0, x0), count=(y1-y0, x1-x0)), dtype=float)
                info = dataset.attributes()
                valid = np.isfinite(raw)
                for key in ('_FillValue', 'missing_value'):
                    if key in info:
                        valid &= ~np.isin(raw, np.asarray(info[key]).ravel())
                if 'valid_range' in info:
                    low, high = np.asarray(info['valid_range']).ravel()[:2]
                    valid &= (raw >= low) & (raw <= high)
                if 'valid_min' in info:
                    valid &= raw >= float(info['valid_min'])
                if 'valid_max' in info:
                    valid &= raw <= float(info['valid_max'])
                values = raw * float(info.get('scale_factor', 1)) + float(info.get('add_offset', 0))
                xx, yy = np.meshgrid(ul[0] + (np.arange(x0, x1)+.5)*dx, ul[1] + (np.arange(y0, y1)+.5)*dy)
                if projection == 'SINUSOIDAL':
                    lat = np.degrees(yy / RADIUS)
                    lon = np.degrees(xx / (RADIUS * np.cos(yy / RADIUS)))
                else:
                    lon, lat = xx, yy
                valid &= np.isfinite(values) & (lat >= south) & (lat <= north) & (lon >= west) & (lon <= east)
                for i, j in zip(*np.nonzero(valid)):
                    output.append(dict(latitude=float(lat[i,j]), longitude=float(lon[i,j]), value=float(values[i,j]), variable=name, unit=str(info.get('units', ''))))
            finally:
                dataset.endaccess()
        return dict(rows=output, sourceRows=source_rows, coordinateBackend='Original HDF4 HDF-EOS grid')
    finally:
        source.end()
