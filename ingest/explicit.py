import os
import sys
import tarfile
import shutil
from lxml import html
from datetime import datetime as dt
from requests import get
from urllib import urlparse, urlunparse

sys.path.append(os.path.dirname(__file__))

SATS = ['LANDSAT_1', 'LANDSAT_2', 'LANDSAT_3', 'LANDSAT_4',
        'LANDSAT_5', 'LANDSAT_7', 'LANDSAT_8']

WRS_1 = os.path.join(os.path.dirname(__file__), 'wrs', 'wrs1_descending.shp')
WRS_2 = os.path.join(os.path.dirname(__file__), 'wrs', 'wrs2_descending.shp')
WRS_DIR = os.path.join(os.path.dirname(__file__), 'wrs')

SCENES = os.path.join(os.path.dirname(__file__), 'scenes')

fmt = '%Y-%m-%d'


class GCDownload(object):
    def __init__(self, start, end, satellite, latitude=None, longitude=None,
                 path=None, row=None, max_cloud_percent=100,
                 instrument=None, output_path=None, zipped=False, alt_name=False):

        self.sat_num = satellite
        self.sat_name = 'LANDSAT_{}'.format(self.sat_num)
        self.instrument = instrument
        self.start_str = start
        self.end_str = end
        self.start_dt = dt.strptime(start, fmt)
        self.end_dt = dt.strptime(end, fmt)
        self.cloud = float(max_cloud_percent)

        if satellite < 4:
            self.vectors = WRS_1
        else:
            self.vectors = WRS_2

        self.scenes_abspath = None
        self.scenes = SCENES

        self.p = path
        self.r = row
        self.lat = latitude
        self.lon = longitude
        self._check_pr_lat_lon()

        self.urls_low_cloud = None
        self.product_ids_low_cloud = None
        self.scene_ids_low_cloud = None
        self.scenes_low_cloud = None

        self.urls_all = None
        self.product_ids_all = None
        self.scene_ids_all = None
        self.scenes_all = None

        self.selected_scenes = None
        self.pymetric_ids = None

        self.output = output_path
        self.zipped = zipped
        self.alt_name = alt_name

        self.current_image = None


    def download(self, list_type='all'):

        if list_type == 'low_cloud':
            scenes = self.scenes_low_cloud
        elif list_type == 'all':
            scenes = self.scenes_all
        elif list_type == 'selected':
            scenes = self.selected_scenes

        out_dir = None
        for ind, row in scenes.iterrows():
            print('Image {} for {}'.format(row.SCENE_ID, row.DATE_ACQUIRED))
            for band in self.band_map.file_suffixes[self.sat_name]:

                url = self._make_url(row, band)

                dst = os.path.join(self.output, row.SCENE_ID, os.path.basename(url))

                out_dir = os.path.join(self.output, row.SCENE_ID)
                if not os.path.isdir(out_dir):
                    os.mkdir(out_dir)

                if not os.path.isfile(dst):
                    self._fetch_image(url, dst)

            if self.zipped:
                tgz_file = '{}.tar.gz'.format(row.SCENE_ID)
                self._zip_image(tgz_file, out_dir)

            if self.alt_name:
                tgz_file = '{}.tar.gz'.format(row.PYMETRIC_ID)
                self._zip_image(tgz_file, out_dir)

        return None


    def _check_pr_lat_lon(self):
        if self.p and self.r:
            try:
                self.p, self.r = int(self.p), int(self.r)
            except TypeError:
                pass
        elif self.lat and self.lon:
            self._get_path_row()
        else:
            raise MissingInitData(print('Must create GCDownload object with both path and row,'
                                        'or with both latitude and longitude'))

    def _get_path_row(self):
        """
        :param lat: Latitude float
        :param lon: Longitude float
                'convert_pr_to_ll' [path, row to coordinates]
        :return: lat, lon tuple or path, row tuple
        """
        conversion_type = 'convert_ll_to_pr'
        base = 'https://landsat.usgs.gov/landsat/lat_long_converter/tools_latlong.php'
        unk_number = 1508518830987

        full_url = '{}?rs={}&rsargs[]={}&rsargs[]={}&rsargs[]=1&rsrnd={}'.format(base,
                                                                                 conversion_type,
                                                                                 self.lat, self.lon,
                                                                                 unk_number)
        r = get(full_url)
        tree = html.fromstring(r.text)

        # remember to view source html to build xpath
        # i.e. inspect element > network > find GET with relevant PARAMS
        # > go to GET URL > view source HTML
        p_string = tree.xpath('//table/tr[1]/td[2]/text()')
        self.p = int(re.search(r'\d+', p_string[0]).group())

        r_string = tree.xpath('//table/tr[1]/td[4]/text()')
        self.r = int(re.search(r'\d+', r_string[0]).group())

    @staticmethod
    def _make_url(row, band):

        parse = urlparse('http://storage.googleapis.com/gcp-public-data-landsat/LC08/01/037/029/'
                         'LC08_L1TP_037029_20130101_20190131_01_T1/LC08_L1TP_037029_20130101_20190131_01_T1_B9.TIF')

        base = row.BASE_URL.replace('gs://', '')
        path = '{}/{}_{}'.format(base, row.PRODUCT_ID, band)
        url = urlunparse([parse.scheme, parse.netloc, path, '', '', ''])
        return url

    @staticmethod
    def _fetch_image(url, destination_path=None):

        if not destination_path:
            destination_path = os.path.join(os.getcwd(), os.path.basename(url))

        try:
            response = get(url, stream=True)
            if response.status_code == 200:
                with open(destination_path, 'wb') as f:
                    print('Getting {}'.format(os.path.basename(url)))
                    for chunk in response.iter_content(chunk_size=1024 * 1024 * 8):
                        f.write(chunk)

            elif response.status_code > 399:
                print('Code {} on {}'.format(response.status_code, url))
                raise BadRequestsResponse(Exception)
        except BadRequestsResponse:
            pass

    @staticmethod
    def _zip_image(output_filename, source_dir):
        out_location = os.path.dirname(source_dir)
        with tarfile.open(os.path.join(out_location, output_filename), "w:gz") as tar:
            tar.add(source_dir, arcname=os.path.basename(source_dir))
        shutil.rmtree(source_dir)
