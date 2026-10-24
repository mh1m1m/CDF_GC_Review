"""Draft-only executive exports from the exact dashboard semantic read model.

Native editable Word tables and Excel charts/formulas; static artwork is labelled.
No exporter creates issuance authority, approval, or human signatures.
"""
from io import BytesIO
import json
from pathlib import Path
import tempfile
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from openpyxl.drawing.image import Image as ExcelImage
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import Workbook
from openpyxl.chart import DoughnutChart, Reference
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Font, PatternFill
from ..release.authorization_gate import mark_working_copy_docx, WORKING_COPY_MARK

LOGO = Path(__file__).resolve().parents[2] / 'apps/web/public/cdf-wordmark-on-light.jpg'
TOKENS = json.loads((Path(__file__).resolve().parents[2] / 'shared/visual-tokens.json').read_text())


def gauge_artwork(data: dict) -> bytes:
    """Static snapshot artwork; values come from the same metric contract as web."""
    from PIL import Image, ImageDraw, ImageFont
    image=Image.new('RGB',(1200,340),'#f1f4f7')
    draw=ImageDraw.Draw(image)
    font=ImageFont.load_default(size=22);large=ImageFont.load_default(size=40)
    for i,metric in enumerate(data['metrics'][:3]):
        x=20+i*395
        draw.rounded_rectangle((x,15,x+375,320),radius=28,fill='#ffffff',outline='#dce6ed',width=2)
        box=(x+100,45,x+275,220)
        draw.arc(box,-90,270,fill='#e4ebf0',width=15)
        if metric['value'] is not None:
            draw.arc(box,-90,-90+3.6*metric['value'],fill=TOKENS['violet'],width=15)
        text='N/A' if metric['value'] is None else str(metric['value'])+'%'
        draw.text((x+188,132),text,font=large,fill=TOKENS['ink'],anchor='mm')
        label=metric['id'].replace('_',' ').upper()
        draw.text((x+188,257),label,font=font,fill=TOKENS['ink'],anchor='mm')
        fraction=str(metric['numerator'])+' / '+str(metric['denominator'])
        draw.text((x+188,292),fraction,font=font,fill=TOKENS['muted'],anchor='mm')
    output=BytesIO();image.save(output,format='PNG');return output.getvalue()


def export_dashboard(data: dict, kind: str) -> bytes:
    if kind not in ('docx', 'xlsx', 'pdf'):
        raise ValueError('UNSUPPORTED_DRAFT_EXPORT')
    if kind == 'xlsx':
        wb = Workbook()
        ws = wb.active; ws.title = 'Executive'
        ws.sheet_view.rightToLeft = True
        wb.properties.category = WORKING_COPY_MARK
        wb.properties.keywords = 'SYNTHETIC INTERNAL DRAFT NOT AUTHORIZED'
        ws.append(['نسخة عمل تجريبية غير معتمدة', data['case_id']])
        if LOGO.is_file():
            logo=ExcelImage(LOGO);logo.height=185*logo.height/logo.width;logo.width=185;ws.add_image(logo,'H1')
        ws.append(['المؤشر', 'البسط', 'المقام', 'النسبة', 'حالة الدليل', 'قيد التفسير'])
        for i, metric in enumerate(data['metrics'], 3):
            ws.append([metric['title'], metric['numerator'], metric['denominator'],
                       f'=IF(OR(B{i}="",C{i}="",C{i}=0),"",B{i}/C{i})', metric['status'], metric['limitation']])
            ws.cell(i, 4).number_format = '0.0%'
        ws.freeze_panes = 'B3'; ws.auto_filter.ref = f'A2:F{ws.max_row}'
        ws.column_dimensions['A'].width=30; ws.column_dimensions['F'].width=70
        for col in 'BCDE': ws.column_dimensions[col].width=22
        # Native editable chart tied to the actual calibration numerator/remaining count.
        calibration = next(m for m in data['metrics'] if m['id']=='calibration')
        chart_data=wb.create_sheet('ChartData'); chart_data.append(['الحالة','العدد'])
        chart_data.append(['معاير', calibration['numerator'] or 0])
        chart_data.append(['متبق', max(0,(calibration['denominator'] or 0)-(calibration['numerator'] or 0))])
        if calibration['denominator']:
            chart=DoughnutChart(); chart.title='تغطية المعايرة — رسم Excel أصلي'; chart.holeSize=75
            chart.add_data(Reference(chart_data,min_col=2,min_row=1,max_row=3),titles_from_data=True)
            chart.set_categories(Reference(chart_data,min_col=1,min_row=2,max_row=3)); ws.add_chart(chart,'A12')
        risk=wb.create_sheet('Materiality'); risk.sheet_view.rightToLeft=True
        risk.append(['التصنيف','قيد المعايرة','قرار مقدم'])
        for item in data['heatmap']: risk.append([item['category'],item['pending'],item['submitted']])
        if risk.max_row>1:
            risk.conditional_formatting.add(f'B2:C{risk.max_row}',ColorScaleRule(start_type='min',start_color='FFFFFF',end_type='max',end_color=TOKENS['salmon'][1:]))
        evidence=wb.create_sheet('Evidence'); evidence.append(['المعرف','نوع المصدر','الموضع','حالة الاعتماد','قابلية التطبيق'])
        for item in data['evidence']:
            evidence.append([item['id'],item['kind'],item['page_or_paragraph'],item['approval_status'],item['applicability']])
        debate=wb.create_sheet('Debate');debate.append(['الملاحظة','الاعتراض','الدورات','الحسم','المبرر'])
        for item in data['objections']:debate.append([item['observation_id'],item['id'],item['productive_cycles'],item['disposition'],item['rationale']])
        journal=wb.create_sheet('Timeline');journal.append(['الحدث','الوقت','الملاحظة'])
        for event in data['timeline']:journal.append([event['kind'],event['at'],event['observation_id']])
        lifecycle=wb.create_sheet('Observations');lifecycle.append(['المعرف','الأصل','المعاد','التغير المرصود','قرار المعايرة'])
        for item in data['observations']:lifecycle.append([item['observation_id'],item.get('original_text'),item.get('reviewed_text'),item.get('observed_change'),(item.get('calibration') or {}).get('decision')])
        lifecycle.auto_filter.ref=f'A1:E{lifecycle.max_row}';lifecycle.freeze_panes='B2'
        provenance=wb.create_sheet('Provenance'); provenance.append(['العقد',data['schema']]); provenance.append(['إصدار؟','NOT_AUTHORIZED'])
        provenance.append(['مصدر البيانات','SYNTHETIC']); provenance.append(['حالة الهوية البصرية',TOKENS['classification']])
        provenance.append(['بصمة الأدلة',data['evidence_hash']]); provenance.append(['معرف التشغيل',data['run_id']])
        for sheet in wb:
            sheet.sheet_view.rightToLeft=True
            for row in sheet:
                for cell in row:
                    if isinstance(cell.value,str) and not (sheet == ws and cell.column == 4 and cell.row >= 3):
                        cell.data_type='s'
                    cell.font=Font(name='Calibri',size=11,color=TOKENS['ink'][1:])
            for cell in sheet[1]: cell.fill=PatternFill('solid',fgColor=TOKENS['blue'][1:])
        output=BytesIO();wb.save(output);return output.getvalue()
    with tempfile.TemporaryDirectory(prefix='cdf-executive-draft-') as temp:
        path=Path(temp)/'INTERNAL_DRAFT__executive.docx'
        doc=Document()
        if LOGO.is_file():
            header=doc.sections[0].header.paragraphs[0];header.alignment=WD_ALIGN_PARAGRAPH.RIGHT;header.add_run().add_picture(str(LOGO),width=Inches(2.2))
        doc.core_properties.title='مركز الذكاء الحوكمي — نسخة تجريبية'
        doc.add_heading('مركز الذكاء الحوكمي',0)
        doc.add_paragraph('SYNTHETIC · INTERNAL DRAFT · NOT AUTHORIZED FOR ISSUE')
        doc.add_paragraph('بيانات تجريبية؛ لا تمثل اعتماداً مؤسسياً أو توقيعاً بشرياً.')
        doc.add_picture(BytesIO(gauge_artwork(data)), width=Inches(6.1))
        doc.add_paragraph('رسوم ثابتة من لقطة البيانات؛ الجدول التالي قابل للتحرير.')
        doc.add_paragraph(f"Case: {data['case_id']} | Run: {data['run_id'] or 'NOT_RUN'}")
        table=doc.add_table(rows=1, cols=4);table.style='Light Shading Accent 1'
        for c,t in zip(table.rows[0].cells,['المؤشر','البسط / المقام','النسبة','الحالة']): c.text=t
        for metric in data['metrics']:
            cells=table.add_row().cells
            cells[0].text=metric['title']
            numerator='غير متاح' if metric['numerator'] is None else str(metric['numerator'])
            denominator='غير متاح' if metric['denominator'] is None else str(metric['denominator'])
            cells[1].text=f'البسط: {numerator}؛ المقام: {denominator}'
            cells[2].text='غير مقاس' if metric['value'] is None else f"{metric['value']}%";cells[3].text=metric['status']
            doc.add_paragraph(metric['title']+': '+metric['limitation'])
        doc.add_heading('النقاش والأدلة',1)
        debate=doc.add_table(rows=1,cols=4);debate.style='Light Shading Accent 1'
        for cell,text in zip(debate.rows[0].cells,['الملاحظة','دورات منتجة','الحسم المسجل','المبرر']):cell.text=text
        for objection in data['objections']:
            row=debate.add_row().cells
            for cell,text in zip(row,[objection['observation_id'],str(objection['productive_cycles']),objection['disposition'],objection['rationale'] or 'غير مسجل']):cell.text=str(text)
        doc.add_heading('حدود الإصدار وسلسلة الإثبات',1)
        for reason in data['release_gate']['reasons']:doc.add_paragraph(reason,style='List Bullet')
        doc.add_paragraph('Evidence hash: '+data['evidence_hash'])
        doc.add_paragraph('Visual classification: '+TOKENS['classification'])
        for table in doc.tables:
            bidi=OxmlElement('w:bidiVisual');bidi.set(qn('w:val'),'1');table._tbl.tblPr.append(bidi)
        paragraphs=list(doc.paragraphs)+[p for table in doc.tables for row in table.rows for cell in row.cells for p in cell.paragraphs]
        for paragraph in paragraphs:
            props=paragraph._p.get_or_add_pPr();rtl=OxmlElement('w:bidi');rtl.set(qn('w:val'),'1');props.append(rtl)
            for run in paragraph.runs:run.font.name='Calibri';run.font.size=Pt(11);run.font.color.rgb=RGBColor.from_string(TOKENS['ink'][1:])
        doc.sections[0].footer.paragraphs[0].text=WORKING_COPY_MARK
        doc.save(path);mark_working_copy_docx(path)
        if kind=='pdf':
            from ..qa.lo_engine import to_pdf
            pdf=to_pdf(path,Path(temp)/'pdf',timeout=60)
            if pdf is None:raise RuntimeError('DRAFT_PDF_RENDER_FAILED')
            return pdf.read_bytes()
        return path.read_bytes()
