import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from pyhdf.SD import SD, SDC
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from native_hdf4 import convert, _degrees
from server import app
from fastapi.testclient import TestClient


def fixture(path, projection='GCTP_GEO'):
    f = SD(str(path), SDC.WRITE | SDC.CREATE)
    d = f.create('NDVI', SDC.INT16, (2,2))
    d[:] = np.array([[5000,-3000],[10000,12000]], dtype=np.int16)
    d.attributes()
    d.attr('scale_factor').set(SDC.FLOAT64,.0001)
    d.attr('_FillValue').set(SDC.INT16,-3000)
    d.attr('valid_range').set(SDC.INT16,[-2000,10000])
    d.attr('units').set(SDC.CHAR,'NDVI')
    ul, lr = ('(90000000, 24000000)', '(91000000, 23000000)')
    if projection=='GCTP_SNSOID':
        from native_hdf4 import RADIUS
        ul,lr = f'(0, {RADIUS*np.pi/180})', f'({RADIUS*np.pi/180}, 0)'
    f.attr('StructMetadata.0').set(SDC.CHAR,f'''GROUP=GRID_1
XDim=2
YDim=2
UpperLeftPointMtrs={ul}
LowerRightMtrs={lr}
Projection={projection}
DataFieldName="NDVI"
END_GROUP=GRID_1''')
    d.endaccess();f.end()


class NativeTests(unittest.TestCase):
    def test_exact_geographic_hdf4_scaling_fill_clipping(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'MOD13C1.hdf';fixture(p)
            result=convert(p,['ndvi'],[90,23,91,24])
            self.assertEqual(result['sourceRows'],4)
            self.assertEqual([x['value'] for x in result['rows']],[.5,1])
            self.assertEqual(result['rows'][0]['latitude'],23.75)
            self.assertEqual(result['rows'][0]['longitude'],90.25)
            self.assertEqual(convert(p,['ndvi'],[80,10,81,11])['rows'],[])
            with self.assertRaisesRegex(ValueError,'matches'):
                convert(p,['no2'],[90,23,91,24])
    def test_sinusoidal_hdf4(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'MOD13A2.hdf';fixture(p,'GCTP_SNSOID')
            result=convert(p,['ndvi'],[0,0,2,2])
            self.assertEqual(len(result['rows']),2)
            self.assertAlmostEqual(result['rows'][0]['latitude'],.75)
            self.assertAlmostEqual(result['rows'][0]['longitude'],.25/np.cos(np.deg2rad(.75)))
    def test_packed_dms(self):
        self.assertAlmostEqual(_degrees(123030000),123.5)
        self.assertAlmostEqual(_degrees(-90015000),-90.25)
    def test_binary_http_endpoint(self):
        client=TestClient(app)
        formats=client.get('/health').json()['formats'];self.assertIn('hdf4',formats);self.assertIn('hdf5',formats);self.assertIn('netcdf',formats);self.assertIn('geotiff',formats);self.assertIn('ascii',formats);self.assertIn('json',formats);self.assertIn('zarr',formats)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.hdf';fixture(p)
            response=client.post('/convert',params={'component':'NDVI','bbox':'[90,23,91,24]'},content=p.read_bytes(),headers={'Content-Type':'application/octet-stream','Origin':'https://rakatashraf.github.io'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(response.json()['rows']),2)
        self.assertEqual(client.post('/convert',params={'component':'NDVI','bbox':'[90,23,91,24]'},content=b'not hdf').status_code,415)
        self.assertEqual(client.post('/convert',params={'component':'NDVI','bbox':'[90,23,91,24]'},content=b'',headers={'Origin':'https://untrusted.example'}).status_code,403)

if __name__=='__main__':unittest.main()
