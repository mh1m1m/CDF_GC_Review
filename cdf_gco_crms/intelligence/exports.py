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
from openpyxl.chart.series import DataPoint
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
import zipfile
from lxml import etree
from ..release.authorization_gate import mark_working_copy_docx, WORKING_COPY_MARK

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
    from ..documents.policy import is_uploaded_case, site_identity
    uploaded = is_uploaded_case(data.get('case_id'))
    if data.get('synthetic') is not True and not uploaded:
        raise PermissionError('PRIVATE_EXPORT_REQUIRES_AUTHORIZED_WORKSPACE')
    if uploaded and site_identity() == 'CDF':
        # The owner's branded deployment: an uploaded document's dashboard carries the institution's wordmark.
        logo = institution_wordmark_png()
        if logo:
            from ..institutional.providers import PublicSyntheticProvider
            return _render_dashboard({**data, 'reference_catalog': PublicSyntheticProvider().catalog()}, kind, logo=logo)
    from ..institutional.providers import PublicSyntheticProvider
    data={**data,'reference_catalog':PublicSyntheticProvider().catalog()}
    # Synthetic exports carry a neutral demo mark, never an institution's wordmark (audit C5); the authorised
    # private workspace supplies its own brand asset through its own provider.
    return _render_dashboard(data,kind,logo=demo_mark_png())


def brand_wordmark_path() -> Path:
    return Path(__file__).resolve().parents[2] / 'shared' / 'brand' / 'cdf-wordmark-on-light.png'


def institution_wordmark_png() -> bytes | None:
    """The CDF wordmark (light background) from shared/brand, as PNG; None when it is not deployed."""
    from PIL import Image

    path = brand_wordmark_path()
    try:
        image = Image.open(path).convert('RGB')
    except OSError:
        return None
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def demo_mark_png() -> bytes:
    """Neutral public-demo mark, generated so no image binary is committed: same 1139x225 proportions as the
    institutional wordmark slot, light background, Latin text only (rendered without a shaping engine)."""
    from PIL import Image, ImageDraw, ImageFont
    image=Image.new('RGB',(1139,225),'white')
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((6,6,1132,218),radius=28,outline=(60,72,88),width=6)
    try:
        big,small=ImageFont.load_default(size=78),ImageFont.load_default(size=38)
    except TypeError:            # Pillow without sized default fonts
        big=small=ImageFont.load_default()
    draw.text((1090,92),'SYNTHETIC DEMO',font=big,fill=(30,40,55),anchor='rm')
    draw.text((1090,165),'NOT AN OFFICIAL DOCUMENT',font=small,fill=(70,82,98),anchor='rm')
    output=BytesIO();image.save(output,format='PNG');return output.getvalue()


def _render_dashboard(data: dict, kind: str, *, logo: bytes) -> bytes:
    classification='SYNTHETIC' if data.get('synthetic') else 'PRIVATE INSTITUTIONAL'
    catalog=data.get('reference_catalog',{'sources':[],'authorities':[],'units':[]})
    if kind not in ('docx', 'xlsx', 'pdf'):
        raise ValueError('UNSUPPORTED_DRAFT_EXPORT')
    if kind == 'xlsx':
        wb = Workbook()
        ws = wb.active; ws.title = 'Executive'
        ws.sheet_view.rightToLeft = True
        wb.properties.category = WORKING_COPY_MARK
        wb.properties.keywords = classification+' INTERNAL DRAFT NOT AUTHORIZED'
        ws.append(['نسخة عمل غير مصرح بإصدارها · '+classification, data['case_id']])
        if logo:
            image=ExcelImage(BytesIO(logo));image.height=185*image.height/image.width;image.width=185;ws.add_image(image,'H1')
        ws.append(['المؤشر', 'البسط', 'المقام', 'النسبة', 'حالة الدليل', 'قيد التفسير'])
        for i, metric in enumerate(data['metrics'], 3):
            ws.append([metric['title'], metric['numerator'], metric['denominator'],
                       f'=IF(OR(B{i}="",C{i}="",C{i}=0),"",B{i}/C{i})', metric['status'], metric['limitation']])
            ws.cell(i, 4).number_format = '0.0%'
        table=Table(displayName='ExecutiveMetrics',ref=f'A2:F{ws.max_row}');table.tableStyleInfo=TableStyleInfo(name='TableStyleMedium2',showRowStripes=True);ws.add_table(table)
        for row in ws.iter_rows(min_row=3,max_row=ws.max_row):
            ws.row_dimensions[row[0].row].height=48
            for cell in row:cell.alignment=Alignment(wrap_text=True,vertical='center')
        ws.freeze_panes = 'B3'; ws.auto_filter.ref = f'A2:F{ws.max_row}'
        ws.column_dimensions['A'].width=30; ws.column_dimensions['F'].width=70
        for col in 'BCDE': ws.column_dimensions[col].width=22
        # Native editable chart tied to the actual calibration numerator/remaining count.
        calibration = next(m for m in data['metrics'] if m['id']=='calibration')
        chart_data=wb.create_sheet('ChartData'); chart_data.append(['الحالة','العدد'])
        chart_data.append(['معاير', calibration['numerator'] or 0])
        chart_data.append(['متبق', max(0,(calibration['denominator'] or 0)-(calibration['numerator'] or 0))])
        if calibration['denominator']:
            chart=DoughnutChart(); chart.title='تغطية المعايرة'; chart.holeSize=75
            chart.add_data(Reference(chart_data,min_col=2,min_row=1,max_row=3),titles_from_data=True)
            chart.set_categories(Reference(chart_data,min_col=1,min_row=2,max_row=3))
            for index,color in enumerate([TOKENS['violet'],TOKENS['blue']]):
                point=DataPoint(idx=index);point.graphicalProperties.solidFill=color[1:];chart.series[0].data_points.append(point)
            ws.add_chart(chart,'A12')
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
        journal.cell(1,4,'تراكم الأحداث المسجلة')
        for i,event in enumerate(data['timeline'],1):journal.append([event['kind'],event['at'],event['observation_id'],i])
        lifecycle=wb.create_sheet('Observations');lifecycle.append(['المعرف','الأصل','المعاد','التغير المرصود','قرار المعايرة','التصنيف المادي','التوصية','المراجع','إجراء المراجع المحلي','الصياغة المسجلة','هوية الجلسة التجريبية','إصدار القرار'])
        for item in data['observations']:lifecycle.append([item['observation_id'],item.get('original_text'),item.get('reviewed_text'),item.get('observed_change'),(item.get('calibration') or {}).get('decision'),', '.join(item.get('material_categories',[])),str(item.get('original_text') or '').partition('التوصية:')[2].strip(),', '.join(item.get('authority_reference_ids',[])+item.get('department_reference_ids',[])),(item.get('human_review') or {}).get('action'),(item.get('human_review') or {}).get('final_wording'),(item.get('human_review') or {}).get('actor'),(item.get('human_review') or {}).get('version')])
        lifecycle.auto_filter.ref=f'A1:L{lifecycle.max_row}';lifecycle.freeze_panes='B2'
        sources=wb.create_sheet('ReferenceSources');sources.append(['مرجع للفهرسة فقط؛ لا يثبت إسناد الملاحظة','الإصدار','الاعتماد','السريان','عدم الاستبدال'])
        for source in catalog['sources']:sources.append([source['id'],source['version'],source['approval_status'],source['effective_date'],str(source['supersession_checked'])])
        authorities=wb.create_sheet('AuthorityMap');authorities.append(['المعرف','النشاط','الجهة','الدور الموثق','الصفحة','المصدر'])
        for item in catalog['authorities']:
            for body,role in item['roles'].items():authorities.append([item['id'],item['title'],body,role,item['page'],item['source_id']])
        mandates=wb.create_sheet('ResponsibilityMap');mandates.append(['المعرف','الوحدة','القطاع','المهمة','الصفحة','المصدر'])
        for item in catalog['units']:
            for task in item['tasks'] or ['NOT_DOCUMENTED']:mandates.append([item['id'],item['name'],item['sector'],task,item['page'],item['source_id']])
        for label,value,at in [('ملاحظات مسجلة',data['observation_count'],3),('ملاحظات مادية مفتوحة',len(data['unresolved_material']),7)]:
            ws.merge_cells(start_row=at,start_column=8,end_row=at,end_column=9);ws.cell(at,8,label)
            ws.merge_cells(start_row=at+1,start_column=8,end_row=at+2,end_column=9);ws.cell(at+1,8,value);ws.cell(at+1,8).fill=PatternFill('solid',fgColor=TOKENS['mint'][1:])
        ws.merge_cells('H12:J12');ws['H12']='تراكم أحداث السجل'
        ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A3;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=1
        ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.print_area='A1:J30'
        provenance=wb.create_sheet('Provenance'); provenance.append(['العقد',data['schema']]); provenance.append(['إصدار؟','NOT_AUTHORIZED'])
        provenance.append(['مصدر البيانات',classification]); provenance.append(['حالة الهوية البصرية',TOKENS['classification']])
        provenance.append(['بصمة الأدلة',data['evidence_hash']]); provenance.append(['معرف التشغيل',data['run_id']])
        for sheet in wb:
            sheet.sheet_view.rightToLeft=True
            for row in sheet:
                for cell in row:
                    if isinstance(cell.value,str) and not (sheet == ws and cell.column == 4 and cell.row >= 3):
                        cell.data_type='s'
                    cell.font=Font(name='Calibri',size=11,color=TOKENS['ink'][1:])
            for cell in sheet[1]: cell.fill=PatternFill('solid',fgColor=TOKENS['blue'][1:])
        ws.sheet_view.showGridLines=False
        for cell in ws[2]:
            if cell.column<=6:cell.fill=PatternFill('solid',fgColor=TOKENS['ink'][1:]);cell.font=Font(name='Calibri',size=12,bold=True,color='FFFFFF');cell.alignment=Alignment(horizontal='center',vertical='center')
        ws.row_dimensions[2].height=30
        for row in ws.iter_rows(min_row=3,max_row=10,max_col=6):
            for cell in row:
                cell.border=Border(bottom=Side(style='hair',color='DDE5EB'))
                cell.alignment=Alignment(horizontal='center' if cell.column in (2,3,4,5) else 'right',wrap_text=True,vertical='center')
        ws.column_dimensions['H'].width=22;ws.column_dimensions['I'].width=14
        for row in (3,7,12):ws.row_dimensions[row].height=36;ws.cell(row,8).alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
        for row in (4,8):ws.cell(row,8).font=Font(name='Calibri',size=26,bold=True,color=TOKENS['ink'][1:]);ws.cell(row,8).alignment=Alignment(horizontal='center',vertical='center')
        output=BytesIO();wb.save(output)
        return _with_sparkline(output.getvalue(),len(data['timeline']))
    with tempfile.TemporaryDirectory(prefix='cdf-executive-draft-') as temp:
        path=Path(temp)/'INTERNAL_DRAFT__executive.docx'
        doc=Document()
        if logo:
            header=doc.sections[0].header.paragraphs[0];header.alignment=WD_ALIGN_PARAGRAPH.RIGHT;header.add_run().add_picture(BytesIO(logo),width=Inches(2.2))
        doc.core_properties.title='مركز الذكاء الحوكمي — نسخة عمل غير مصدرة'
        doc.add_heading('مركز الذكاء الحوكمي',0)
        doc.add_paragraph(classification+' · INTERNAL DRAFT · NOT AUTHORIZED FOR ISSUE')
        doc.add_paragraph('بيانات تجريبية؛ لا تمثل اعتماداً مؤسسياً أو توقيعاً بشرياً.' if data.get('synthetic') else 'نسخة مؤسسية داخلية للمراجعة؛ لا تمثل تصريحاً بالإصدار أو اعتماداً مهنياً.')
        doc.add_picture(BytesIO(gauge_artwork(data)), width=Inches(6.1))
        doc.add_paragraph('رسوم ثابتة من لقطة البيانات؛ الجدول التالي قابل للتحرير.')
        doc.add_paragraph(f"Case: {data['case_id']} | Run: {data['run_id'] or 'NOT_RUN'}")
        doc.add_paragraph('من السجل إلى القرار · لقطة تنفيذ وأدلة ومعايرة قابلة للتتبع')
        doc.add_page_break()
        table=doc.add_table(rows=1, cols=4);table.style='Light Shading Accent 1'
        for c,t in zip(table.rows[0].cells,['المؤشر','البسط / المقام','النسبة','الحالة']): c.text=t
        for metric in data['metrics']:
            cells=table.add_row().cells
            cells[0].text=metric['title']
            numerator='غير متاح' if metric['numerator'] is None else str(metric['numerator'])
            denominator='غير متاح' if metric['denominator'] is None else str(metric['denominator'])
            cells[1].text=f'البسط: {numerator}؛ المقام: {denominator}'
            doc.add_comment(cells[0].paragraphs[0].runs,text='Automated draft lineage: '+', '.join(metric['lineage'])+'; '+metric['limitation'],author='CDF automated draft provenance',initials='SYS')
            cells[2].text='غير مقاس' if metric['value'] is None else f"{metric['value']}%";cells[3].text=metric['status']
            doc.add_paragraph(metric['title']+': '+metric['limitation'])
        doc.add_heading('الملاحظات والتوصيات — مسودة قابلة للتحرير',1)
        for observation in data['observations']:
            doc.add_heading(observation['observation_id'],2)
            doc.add_paragraph('التصنيف المادي: '+', '.join(observation.get('material_categories',[])))
            doc.add_paragraph(str(observation.get('original_text') or ''))
            human=observation.get('human_review')
            if human:
                doc.add_paragraph('قرار جلسة مراجعة تجريبية — ليس توقيعاً أو تصريح إصدار: '+human['action'])
                doc.add_paragraph('الصياغة المسجلة: '+human['final_wording'])
                doc.add_paragraph('Review version: '+human['version']+' | Actor: '+human['actor'])

            refs=observation.get('authority_reference_ids',[])+observation.get('department_reference_ids',[])
            doc.add_paragraph('مراجع افتراضية غير ملزمة: '+', '.join(refs))
            doc.add_paragraph('موضع النص: '+str(observation.get('location','')))
        doc.add_heading('سجل الأدلة — حالة المصدر محفوظة',1)
        for evidence in data['evidence']:
            doc.add_paragraph(str(evidence['id'])+' · '+str(evidence.get('page_or_paragraph',''))+' · '+str(evidence.get('approval_status','UNVERIFIED')))
        doc.add_heading('النقاش والأدلة',1)
        debate=doc.add_table(rows=1,cols=4);debate.style='Light Shading Accent 1'
        for cell,text in zip(debate.rows[0].cells,['الملاحظة','دورات منتجة','الحسم المسجل','المبرر']):cell.text=text
        for objection in data['objections']:
            row=debate.add_row().cells
            for cell,text in zip(row,[objection['observation_id'],str(objection['productive_cycles']),objection['disposition'],objection['rationale'] or 'غير مسجل']):cell.text=str(text)
        doc.add_heading('خرائط المصدر والصلاحيات والمسؤوليات',1)
        doc.add_paragraph('فهرس مرجعي فقط؛ الإدراج لا يثبت إسناد ملاحظة أو اعتماد صلاحية. العرض التالي محدود إلى ثمانية سجلات من كل نوع.')
        source_table=doc.add_table(rows=1,cols=3);source_table.style='Light Shading Accent 1'
        for cell,text in zip(source_table.rows[0].cells,['المصدر','الإصدار','حالة الاعتماد']):cell.text=text
        for source in catalog['sources']:
            for cell,text in zip(source_table.add_row().cells,[source['id'],source['version'],source['approval_status']]):cell.text=str(text)
        for item in catalog['authorities'][:8]:
            doc.add_paragraph(item['title']+' · '+item['source_id']+' · ص. '+str(item['page']))
            doc.add_paragraph('؛ '.join(body+': '+role for body,role in item['roles'].items()))
        for item in catalog['units'][:8]:
            doc.add_paragraph(item['name']+' · '+item['sector']+' · ص. '+str(item['page']))
            for task in item['tasks'][:4]:doc.add_paragraph(task,style='List Bullet')
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


def _with_sparkline(content: bytes, events: int) -> bytes:
    """Native Excel x14 sparkline from actual event counts, not static artwork.

    LibreOffice/openpyxl may drop this extension when resaving; the original
    delivered XLSX retains the editable Excel element and its source cells.
    """
    if events<2:return content
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    x14='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
    xm='http://schemas.microsoft.com/office/excel/2006/main'
    output=BytesIO()
    with zipfile.ZipFile(BytesIO(content)) as source,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data=source.read(info.filename)
            if info.filename=='xl/worksheets/sheet1.xml':
                root=etree.fromstring(data,etree.XMLParser(resolve_entities=False,no_network=True))
                extension_list=etree.SubElement(root,'{'+ns+'}extLst')
                extension=etree.SubElement(extension_list,'{'+ns+'}ext',uri='{05C60535-1F16-4FD2-B633-F4F36F0B64E0}')
                groups=etree.SubElement(extension,'{'+x14+'}sparklineGroups',nsmap={'x14':x14,'xm':xm})
                group=etree.SubElement(groups,'{'+x14+'}sparklineGroup',displayEmptyCellsAs='gap')
                etree.SubElement(group,'{'+x14+'}colorSeries',rgb='FF'+TOKENS['violet'][1:])
                lines=etree.SubElement(group,'{'+x14+'}sparklines')
                line=etree.SubElement(lines,'{'+x14+'}sparkline')
                etree.SubElement(line,'{'+xm+'}f').text=f"'Timeline'!D2:D{events+1}"
                etree.SubElement(line,'{'+xm+'}sqref').text='H13'
                data=etree.tostring(root,encoding='utf-8')
            target.writestr(info,data)
    return output.getvalue()
