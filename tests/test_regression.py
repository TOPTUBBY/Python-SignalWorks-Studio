"""Run with: python -m unittest discover -s tests -v"""
import builtins
import io
import json
import math
import unittest
import zipfile
from unittest.mock import patch
import xml.etree.ElementTree as ET

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from fastapi.testclient import TestClient
import SignalWorks_Studio_webserv_v4_4_5 as sw

CSV = b'Timestamp,Temp,Voltage\n01.09.2026 23:59:59,20,400\n02.09.2026 00:00:01,30,410\n02.09.2026 00:00:02.500,40,420\n'

class Regression(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(sw.app)
        self.client.post('/upload', files={'file': ('logger.csv', CSV, 'text/csv')})
        self.state = sw.SESSIONS[self.client.cookies[sw.SESSION_COOKIE]]
        self.form = {'selected_0':'on','selected_1':'on','axis_0':'left','axis_1':'right',
                     'line_style_0':'dot','line_style_1':'solid'}
        self.client.post('/update/0', data=self.form)

    def tearDown(self):
        self.client.close()
        sw.SESSIONS.pop(self.state.sid, None)
        plt.close('all')

    def test_baseline_and_upload_dates(self):
        health = self.client.get('/api/health').json()
        self.assertEqual(health['version'], 'V4.4.5.2026')
        self.assertEqual(sw.DEFAULT_PORT, 8800)
        self.assertEqual(list(self.state.df.index.month), [9,9,9])
        self.assertEqual(list(self.state.df.index.day), [1,2,2])
        self.assertEqual((self.state.df.index[1]-self.state.df.index[0]).total_seconds(), 2)

    def test_dotted_invalid_and_fractional_rows(self):
        dates = ['31.08.2026 23:59:59', '01.09.2026_00:00:01',
                 '01.09.2026 00:00:02.500', '31.02.2026 00:00:00', None, 'bad']
        conv, count, _ = sw._best_datetime_conversion(pd.DataFrame({'Date':dates}), 'Date')
        self.assertEqual(count, 3)
        self.assertEqual(list(conv.iloc[:3].dt.month), [8,9,9])
        self.assertEqual(conv.iloc[2].microsecond, 500000)
        self.assertTrue(conv.iloc[3:].isna().all())

    def test_existing_timestamp_formats(self):
        for fmt in ['%d/%m/%Y_%H:%M:%S','%Y-%m-%d_%H:%M:%S',
                    '%Y-%m-%d_%H-%M-%S','%Y-%m-%d %H:%M:%S']:
            with self.subTest(fmt=fmt):
                expected = pd.date_range('2026-09-01 23:59:59', periods=2, freq='2s')
                conv, count, _ = sw._best_datetime_conversion(pd.DataFrame({'Timestamp':expected.strftime(fmt)}),'Timestamp')
                self.assertEqual(count, 2)
                self.assertEqual(list(conv), list(expected))

    def test_separate_date_time(self):
        df = pd.DataFrame({'Date':['01.09.2026','02.09.2026'], 'Time':['23:59:59','00:00:01']})
        conv, count, label = sw._best_datetime_conversion(df,'Date')
        self.assertEqual(count, 2)
        self.assertEqual(label,'Date + Time')
        self.assertEqual((conv.iloc[1]-conv.iloc[0]).total_seconds(),2)

    def test_line_style_and_legacy_preset(self):
        fig = sw.build_interactive_figure(self.state,0)
        self.assertEqual([t.line.dash for t in fig.data], ['dot','solid'])
        static = sw.build_figure(self.state,0)
        self.assertEqual(static.axes[0].lines[0].get_linestyle(), ':')
        self.assertEqual(static.axes[1].lines[0].get_linestyle(), '-')
        payload = sw.build_preset_payload_from_state(self.state)
        self.state.loaded_preset = payload
        sw.apply_loaded_preset(self.state)
        self.assertEqual(self.state.tabs[0].line_style_assignments['Temp'],'dot')
        for fmt in ['GraphPlotSignalPreset','CSVDataPlotterPreset']:
            payload['format'] = fmt
            for tab in payload['tabs']:
                for entry in tab['signals']:
                    entry.pop('line_style',None)
            self.state.loaded_preset = payload
            sw.apply_loaded_preset(self.state)
            self.assertEqual(self.state.tabs[0].line_style_assignments,{})
            self.assertEqual(sw._effective_signal_dash(self.state.tabs[0],'Temp','left',0),'solid')
            self.assertEqual(sw._effective_signal_dash(self.state.tabs[0],'Voltage','right',0),'dash')

    def test_legends_max_three_rows(self):
        for n in [1,3,4,7,10,16,40,100]:
            self.assertLessEqual(math.ceil(n/sw.compact_legend_ncol(n)),3)

    def test_gui_legends_use_separate_axis_containers(self):
        fig = self.client.get('/api/plot/0').json()
        self.assertEqual([(t['name'],t['legend']) for t in fig['data']],
                         [('Temp','legend'),('Voltage','legend2')])
        self.assertEqual(fig['layout']['legend']['title']['text'],'PRIMARY')
        self.assertEqual(fig['layout']['legend2']['title']['text'],'SECONDARY')
        self.assertTrue(fig['layout']['showlegend'])
        self.assertTrue(all('legendgrouptitle' not in t for t in fig['data']))
        self.client.post('/update/0', data={'selected_1':'on','axis_1':'right'})
        fig = self.client.get('/api/plot/0').json()
        self.assertEqual(fig['data'][0]['legend'],'legend2')
        self.assertEqual(fig['layout']['legend2']['title']['text'],'SECONDARY')

    def test_long_legends_do_not_overlap(self):
        self.state.df = pd.DataFrame({f'Long_Signal_Name_{i}':[i,i+1,i+2] for i in range(16)})
        tab = self.state.tabs[0]
        tab.selected_signals = list(self.state.df)
        tab.axis_assignments = {name:'left' if i<8 else 'right' for i,name in enumerate(self.state.df)}
        fig = sw.build_figure(self.state,0)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = [ax.get_legend().get_window_extent(renderer) for ax in fig.axes]
        self.assertFalse(boxes[0].overlaps(boxes[1]))
        for ax in fig.axes:
            rows = {round(text.get_window_extent(renderer).y0) for text in ax.get_legend().get_texts()}
            self.assertLessEqual(len(rows),3)
        interactive = sw.build_interactive_figure(self.state,0)
        self.assertEqual(interactive.layout.legend.traceorder,'normal')

    def test_static_view_limits_visibility_and_cache(self):
        view = {'xaxis_range':['2026-09-02 00:00:00','2026-09-02 00:00:02'],
                'yaxis_range':[25,35], 'yaxis2_range':[405,415],
                'visible_signals':{'Temp':True,'Voltage':False}}
        fig = sw.build_figure(self.state,0,view_state=view)
        self.assertEqual(fig.axes[0].get_ylim(),(25,35))
        self.assertEqual(fig.axes[1].get_ylim(),(405,415))
        self.assertEqual(len(fig.axes[1].lines),0)
        self.assertAlmostEqual(fig.axes[0].get_xlim()[0],mdates.date2num(pd.Timestamp(view['xaxis_range'][0])))
        original = sw.render_plot_png(self.state,0)
        zoomed = sw.render_plot_png(self.state,0,view_state=view)
        self.assertNotEqual(original,zoomed)
        self.assertEqual(sw.render_plot_png(self.state,0),original)

    def test_export_endpoints_forward_view_and_real_files(self):
        view = {'xaxis_range':[0,2], 'yaxis_range':[25,35], 'visible_signals':{'Voltage':False}}
        # Numeric X dataset checks the index-mode export path too.
        self.state.df.index = pd.RangeIndex(len(self.state.df))
        urls = [('/plot/0.png', {'view':json.dumps(view)}, b'\x89PNG'),
                ('/download/plot/0', {'view':json.dumps(view)}, b'\x89PNG'),
                ('/report/pdf', {'tabs':'0,1','views':json.dumps({'0':view})}, b'%PDF'),
                ('/report/pdf-a4', {'tabs':'0,1','views':json.dumps({'0':view})}, b'%PDF'),
                ('/report/word', {'tabs':'0,1','views':json.dumps({'0':view})}, b'PK')]
        for url, params, magic in urls:
            with self.subTest(url=url), patch.object(sw,'build_figure',wraps=sw.build_figure) as builder:
                response = self.client.get(url,params=params)
                self.assertEqual(response.status_code,200,response.text[:100] if response.status_code!=200 else '')
                self.assertTrue(response.content.startswith(magic))
                self.assertEqual(builder.call_args_list[0].kwargs['view_state'],view)
                if magic==b'PK':
                    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                        self.assertIsNone(archive.testzip())
                        ET.fromstring(archive.read('word/document.xml'))

    def test_word_without_python_docx(self):
        original_import = builtins.__import__
        def missing_docx(name,*args,**kwargs):
            if name == 'docx' or name.startswith('docx.'):
                raise ImportError('simulated missing python-docx')
            return original_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=missing_docx):
            response = self.client.get('/report/word?tabs=0,1')
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIsNone(archive.testzip())
            for name in archive.namelist():
                if name.endswith(('.xml','.rels')):
                    ET.fromstring(archive.read(name))
            self.assertEqual(len([n for n in archive.namelist() if n.endswith('.png')]),2)
        from docx import Document
        self.assertEqual(len(Document(io.BytesIO(response.content)).inline_shapes),2)

    def test_views_invalidate_on_axis_reset_and_dataset_changes(self):
        token = self.state.tabs[0].view_token
        self.client.post('/update/0',data={**self.form,'line_style_0':'dash','title':'Styled'})
        self.assertEqual(self.state.tabs[0].view_token,token)
        self.client.post('/update/0',data={**self.form,'left_min':'10','left_max':'50'})
        self.assertNotEqual(self.state.tabs[0].view_token,token)
        token = self.state.tabs[0].view_token
        self.client.post('/reset/0')
        self.assertNotEqual(self.state.tabs[0].view_token,token)
        dataset = self.state.dataset_token
        self.client.post('/upload',files={'file':('new.csv',CSV,'text/csv')})
        self.assertNotEqual(self.state.dataset_token,dataset)

if __name__ == '__main__':
    unittest.main()
