"""Validate source-verified, package-scoped notices without changing MHLW data."""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse
from maker_identity import maker_is_listed_in_row

MAKER_HOSTS = {
    '日東メディック': 'www.nittomedic.co.jp',
    'エーザイ': 'medical2.eisai.jp', '沢井製薬': 'med.sawai.co.jp',
    'EAファーマ': 'www.eapharma.co.jp',
    '丸石製薬': 'www.maruishi-pharm.co.jp',
    '共和薬品工業': 'www.amel-di.com',
    '扶桑薬品工業': 'www.fuso-pharm.co.jp',
    '藤本製薬': 'www.fujimoto-pharm.co.jp',
    '日新製薬': 'www.yg-nissin.co.jp',
    '協和キリン': 'medical.kyowakirin.co.jp',
    '一般社団法人日本血液製剤機構': 'www.jbpo.or.jp',
    '一般社団法人 日本血液製剤機構': 'www.jbpo.or.jp',
    '辰巳化学': 'www.tatsumi-kagaku.com',
    'セオリアファーマ': 'www.ceolia.co.jp',
    'ファイザー': 'www.pfizermedicalinformation.jp', 'サンド': 'sandoz-jp.cms.sandoz.com',
    'サンドファーマ': 'sandoz-jp.cms.sandoz.com',
    '三和化学研究所': 'med.skk-net.com', '日本薬品工業': 'www.npi-inc.co.jp',
    '第一三共': 'www.medicalcommunity.jp', '第一三共エスファ': 'med.daiichisankyo-ep.co.jp',
    '東和薬品': 'med.towayakuhin.co.jp',
    '日本ケミファ': 'www.nc-medical.com',
    '日医工': 'www.nichiiko.co.jp',
    '住友ファーマ': 'sumitomo-pharma.jp',
    '岩城製薬': 'www.iwakiseiyaku.co.jp',
    '杏林製薬': 'www.kyorin-pharm.co.jp',
    'キョーリンリメディオ': 'www.med.kyorin-rmd.com',
    'あすか製薬': 'www.aska-pharma.co.jp',
    '久光製薬': 'www.hisamitsu-pharm.jp',
    '日本ベーリンガーインゲルハイム': 'www.bij-kusuri.jp',
    '日本ジェネリック': 'medical.nihon-generic.co.jp',
    'LTLファーマ': 'www.ltl-pharma.com',
    '太陽ファルマ': 'www.taiyo-pharma.co.jp',
    'ノーベルファーマ': 'www.nobelpharma.co.jp',
    'ニプロ': 'med.nipro.co.jp',
    'テルモ': 'medical.terumo.co.jp',
    '塩野義製薬': 'www.shionogi.com',
    'シオノギファーマ': 'www.shionogi-ph.co.jp',
    'オルガノン': 'organonpro.com',
    'サノフィ': 'www.e-mr.sanofi.co.jp',
    'トーアエイヨー': 'med.toaeiyo.co.jp',
    '吉田製薬': 'www.yoshida-pharm.co.jp',
    'テイカ製薬': 'teika-products.jp',
    'MSD': 'www.msdconnect.jp',
    'アルフレッサ ファーマ': 'www.alfresa-pharma.co.jp',
    '富士製薬工業': 'www.fuji-pharma.jp',
    '高田製薬': 'www.takata-seiyaku.co.jp',
    'コーアイセイ': 'www.koaisei.com',
    '武田薬品工業': 'www.takedamed.com',
    '大原薬品工業': 'www.ohara-ch.co.jp',
    'サンファーマ': 'jp.sunpharma.com',
    'SBカワスミ': 'www.sb-kawasumi.jp',
    'バイエル薬品': 'pharma-navi.bayer.jp',
    '陽進堂ホールディングス': 'yoshindoholdings.co.jp',
    '共創未来ファーマ': 'www.kyosomirai-p.co.jp',
    '大塚製薬工場': 'www.otsukakj.jp',
    'オーファンパシフィック': 'www.orphanpacific.com',
    '旭化成セラピューティクス': 'akp-pharma-digital.com',
    '帝國製薬': 'www.teikoku.co.jp',
    '寿製薬': 'www.kotobuki-pharm.co.jp',
    'チェプラファーム': 'www.cheplapharm.jp',
    '日本化薬': 'mink.nipponkayaku.co.jp',
    '鳥居薬品': 'www.torii.co.jp',
    '三笠製薬': 'www.mikasaseiyaku.co.jp',
    'ビーブランド・メディコーデンタル': 'bee.co.jp',
    'ジーシー昭和薬品': 'www.gc-showayakuhin.com',
    '白水貿易': 'www.hakusui-trading.co.jp',
    '大鵬薬品工業': 'www.taiho.co.jp',
    "T's製薬": 'www.med.ts-pharma.com',
    'グラクソ・スミスクライン': 'gskpro.com',
    'ヴィアトリス・ヘルスケア合同会社': 'www.viatris-e-channel.com',
    'ヴィアトリス製薬合同会社': 'www.viatris-e-channel.com',
}
MAKER_MANUAL_SOURCE_HOSTS = {
    '本草製薬': ('www.honzo.co.jp',),
    '皇漢堂製薬': ('www.kokando.co.jp',),
    '堀井薬品工業': ('www.horii-pharm.co.jp',),
    'マルホ': ('www.maruho.co.jp',),
    'クリニジェン': ('clinigen.co.jp',),
    '千寿製薬': ('www.senju.co.jp',),
    'シオエ製薬': ('www.sioe-pharm.co.jp',),
    '富士製薬工業': ('www.fujipharma.jp',),
    '杏林製薬': ('www.kyorin-medicalbridge.jp',),
    '塩野義製薬': ('med.shionogi.co.jp',),
    # The manufacturer links its drug information to its distributor's site.
    'シオノギファーマ': ('med.shionogi.co.jp', 'www.shionogi.com'),
    'ノバルティスファーマ': ('www.pro.novartis.com',),
    '阪大微生物病研究会': ('www.biken.or.jp',),
    'ビオメディクス': ('biomedix.co.jp',),
    'ロートニッテン': ('www.rohto-nitten.co.jp',),
    # This notice identifies the distributor's packaging and product code.
    'ロートニッテンファーマ': ('www.rohto-nitten.co.jp',),
    '田辺ファーマ': ('medical.tanabe-pharma.com',),
    'Meiji Seika ファルマ': ('meiji-medical-net.com',),
    'セルトリオン・ヘルスケア・ジャパン': ('celltrionhealthcare.jp',),
    '日本臓器製薬': ('www.nippon-zoki.co.jp',),
    '光製薬': ('www.hikari-pharm.co.jp',),
    'あゆみ製薬': ('www.ayumi-pharma.com',),
}
# Specific manufacturer and distributor notices hosted outside the primary company domain.
MAKER_MANUAL_SOURCE_URLS = {
    'クラシエ薬品': {'https://www.kampoyubi.jp/products/20241213_oshirase.pdf'},
    '日東メディック': {'https://www.pmda.go.jp/files/000283184.pdf'},
    '沢井製薬': {'https://www.jga.gr.jp/assets/pdf/medical/supply/63199438957cc967ba228275e96e9825f40fb12c.pdf'},
    "T'sファーマ": {
        'https://www.hospital.or.jp/site/news/file/1693270450.pdf',
        'https://www.med.ts-pharma.com/di-net/kaitei/w_20230828_Budesonide_inhalation_solution_0.5_TT.pdf',
    },
    '佐藤製薬': {
        'https://medinfo-sato.com/update/pdf/241008_pastaron.pdf',
        'https://medinfo-sato.com/update/pdf/260508_pastaron.pdf',
        'https://medinfo-sato.com/update/pdf/260924_pastaron.pdf',
        'https://medinfo-sato.com/update/pdf/261015_pastaron.pdf',
    },
    '科研製薬': {
        'https://medical-pro.kaken.co.jp/product/mentax/documents/mentax_kyokyu_20260708.pdf',
        'https://medical-pro.kaken.co.jp/product/mentax/mentaxcream_chushi_20261019',
        'https://medical-pro.kaken.co.jp/product/prostaglandine/prostaglandine_kyokyu_20260729',
    },
    'Meファルマ': {
        'https://www.meiji-seika-pharma.co.jp/me-pharma/medical/news/pdf/news_230801.pdf',
        'https://www.meiji-seika-pharma.co.jp/me-pharma/medical/news/pdf/news_250924.pdf',
        'https://www.meiji-seika-pharma.co.jp/me-pharma/medical/news/pdf/news_251215.pdf',
        'https://www.meiji-seika-pharma.co.jp/me-pharma/medical/news/pdf/news_260204_02.pdf',
        'https://www.meiji-seika-pharma.co.jp/me-pharma/medical/news/pdf/news_260406.pdf',
        'https://www.meiji-seika-pharma.co.jp/me-pharma/medical/news/pdf/news_260420.pdf',
    },
    '第一三共': {
        'https://oisya3.com/makuhari/wp-content/uploads/2025/02/%E3%81%8A%E3%81%9F%E3%81%B5%E3%81%8F%E3%81%8B%E3%81%9C%E5%87%BA%E8%8D%B7%E5%81%9C%E6%AD%A2-3.pdf',
        'https://www.city.suginami.tokyo.jp/documents/968/otafuku202509daiitisankyou.pdf',
    },
    '小堺製薬': {
        'https://drive.google.com/file/d/17AlzsfqIg9BNdXJxXKcIpM6zuUSi3KSB/view?usp=sharing',
        'https://drive.google.com/file/d/1B6H_4eMDbk0g4tcqnbk79P9nLG3_wgk2/view?usp=sharing',
    },
    '帝人ファーマ': {'https://medical.teijin-pharma.co.jp/content/dam/teijin-medical-web/sites/documents/news/2026/2026060202/LAT_2026060202.pdf'},
    'あすか製薬': {'https://jspe.umin.jp/pdf/news_250901.pdf'},
    'ビーブランド・メディコーデンタル': {'https://medical.nihon-generic.co.jp/uploadfiles/news/JG_product_list.pdf'},
    '全星薬品工業': {
        'https://med.daiichisankyo-ep.co.jp/information/files/1876/%E3%82%A2%E3%82%B8%E3%82%B9%E3%83%AD%E3%83%9E%E3%82%A4%E3%82%B7%E3%83%B3%E9%8C%A0250mg%E3%80%8CDSEP%E3%80%8D%20%20%E9%99%90%E5%AE%9A%E5%87%BA%E8%8D%B7%E3%81%AB%E9%96%A2%E3%81%99%E3%82%8B%E3%81%8A%E7%9F%A5%E3%82%89%E3%81%9B20240312.pdf',
        'https://med.daiichisankyo-ep.co.jp/information/files/2025/EPAZI1N00901-1.pdf',
    },
    '佐藤薬品工業': {
        'https://www.alfresa-pharma.co.jp/news/pdflink/NEWS_ID/2012/',
    },
    '大興製薬': {
        'https://medical.nihon-generic.co.jp/a.php?id=982',
    },
    'メルクバイオファーマ': {'https://funin-fch.net/wp-content/uploads/2023/01/97b4654c172eccff6e25ec66bc0e4343.pdf'},
    '鳥居薬品': {'https://www.jibika.or.jp/uploads/files/hoken_shidakyua_2024.pdf', 'https://www.jibika.or.jp/uploads/files/shida_2025.pdf'},
    'チェプラファーム': {'https://www.nichigan.or.jp/Portals/0/resources/news/Visudyne.pdf'},
    '池田薬品工業': {
        'https://www.nichiiko.co.jp/medicine/file/23650/information/20241204cI2.pdf',
    },
    'ニプロファーマ': {
        'https://www.maruho.co.jp/medical/pdf/products/actosin/news/2609actosin_an.pdf',
        'https://www.nichiiko.co.jp/medicine/file/90840/information/20250514cI6.pdf',
    },
    '日新製薬': {
        'https://med.daiichisankyo-ep.co.jp/information/files/2026/gentei_20250304_E1_G.pdf',
    },
    '日興製薬': {
        'https://nikko-seiyaku.com/nikko_site/wp-content/uploads/2025/02/%E3%80%90%E6%97%A5%E8%88%88%E8%A3%BD%E8%96%AC%E8%B2%A9%E5%A3%B2%E3%80%91%E3%83%95%E3%82%A7%E3%83%8E%E3%83%BC%E3%83%AB%E3%83%BB%E4%BA%9C%E9%89%9B%E8%8F%AF%E3%83%AA%E3%83%8B%E3%83%A1%E3%83%B3%E3%83%88%E3%80%80%E9%99%90%E5%AE%9A%E5%87%BA%E8%8D%B7%E3%81%AB%E9%96%A2%E3%81%99%E3%82%8B%E3%81%8A%E7%9F%A5%E3%82%89%E3%81%9B.pdf',
        'https://nikko-seiyaku.com/nikko_site/wp-content/uploads/2025/05/%E3%80%90%E6%97%A5%E8%88%88%E8%A3%BD%E8%96%AC%E8%B2%A9%E5%A3%B2%E3%80%91%E3%83%95%E3%82%A7%E3%83%8E%E3%83%BC%E3%83%AB%E3%83%BB%E4%BA%9C%E9%89%9B%E8%8F%AF%E3%83%AA%E3%83%8B%E3%83%A1%E3%83%B3%E3%83%88%E3%80%80%E4%BE%9B%E7%B5%A6%E5%81%9C%E6%AD%A2%E3%81%AB%E9%96%A2%E3%81%99%E3%82%8B%E3%81%8A%E7%9F%A5%E3%82%89%E3%81%9B.pdf',
        'https://www.maruishi-pharm.co.jp/medical/media/aenkatannanko_genteishukka_230217.pdf',
        'https://www.maruishi-pharm.co.jp/media/aenkatannanko_chushi_20231013.pdf',
        'https://www.maruishi-pharm.co.jp/medical/media/sucrode-pasta_genteishukka_20260116.pdf',
        'https://med.nipro.co.jp/sfsites/c/sfc/servlet.shepherd/version/download/068Q800001FkBAdIAN',
    },
    'シオノケミカル': {
        'https://www.hikari-pharm.co.jp/wp-content/uploads/2026/03/eto_gv5_2025.12.25.pdf',
        'https://www.nichiiko.co.jp/medicine/file/80935/information/20260422cI1.pdf',
        'https://www.nc-medical.com/product_topics/f4bj0h000000knx2-att/f4bj0h000000knxq.pdf',
    },
    'ブリストル・マイヤーズ スクイブ': {
        'https://www.bmshealthcare.jp/assets/buildeasy/apac-commercial/bms-healthcare-jp/ja/documents/products/kenacort/News_KA2610.pdf',
    },
    'テルモ': {'https://jasect.org/wp/wp-content/uploads/2023/02/23PN005.pdf'},
    'ヤンセンファーマ': {
        'https://www.js-adhd.org/doc/js-adhd/oshirase_20260706.pdf',
        'https://www.js-adhd.org/doc/js-adhd/oshirase_20260723_01.pdf',
    },
    'バイエル薬品': {'https://www.jsge.or.jp/wp-content/uploads/2026/10/43e13de6fd20d8db3390e8f5078a04b8.pdf'},
    '日本イーライリリー': {
        'https://www.nittokyo.or.jp/uploads/files/20261014_Lilly_insulin.pdf',
        'https://www.haigan.gr.jp/wp-content/uploads/2026/06/%E3%83%AC%E3%83%83%E3%83%88%E3%83%B4%E3%82%A3%E3%83%A2%E9%99%90%E5%AE%9A%E5%87%BA%E8%8D%B7%E3%81%8A%E7%9F%A5%E3%82%89%E3%81%9B.pdf',
    },
    '大塚製薬工場': {'https://medical.jms.cc/pdf/customer_information_306.pdf'},
    '大塚製薬': {
        'https://www.otsuka-elibrary.jp/pdf_viewer/?f=%2Finfo%2Ffile%2F241115-information.pdf',
        'https://www.otsuka-elibrary.jp/pdf_viewer/?f=%2Finfo%2Ffile%2F260901-information.pdf',
    },
    '長生堂製薬': {
        'https://medical.nihon-generic.co.jp/uploadfiles/news/JG_product_list.pdf',
        'https://medical.nihon-generic.co.jp/uploadfiles/medicine/TATHI50_CHUUSHI_2602.pdf',
        'https://medical.nihon-generic.co.jp/uploadfiles/medicine/TATHI_CHUUSHI_2507.pdf',
        'https://medical.nihon-generic.co.jp/a.php?id=1725',
        'https://medical.nihon-generic.co.jp/a.php?id=1762',
        'https://medical.nihon-generic.co.jp/a.php?id=1812',
        'https://medical.nihon-generic.co.jp/uploadfiles/medicine/CETIR00_CHUUSHI_2606.pdf',
        'https://medical.nihon-generic.co.jp/a.php?id=1805',
        'https://medical.nihon-generic.co.jp/a.php?id=1841',
        'https://medical.nihon-generic.co.jp/uploadfiles/news/JG_product_list.pdf',
    },
    '日医工ファーマ': {
        'https://www.nichiiko.co.jp/medicine/file/24060/information/20231004cI3.pdf',
    },
    '持田製薬': {
        'https://www.jrs.or.jp/information/file/202408_mochida.pdf',
        'https://www.ayumi-pharma.com/upd/med/doc/325/tcz_info2610.pdf',
        'https://med.mochida.co.jp/etc/img/flo-d202607.pdf',
    },
    '日本薬品工業': {
        'https://www.nc-medical.com/product_topics/f4bj0h000000es1m-att/f4bj0h000000es2a.pdf',
    },
    'ダイト': {
        'https://www.daitonet.co.jp/pdf/medical/pdf_medical_05.pdf',
        'https://www.feldsenfpharma.co.jp/dcms_media/other/%E3%83%86%E3%83%A2%E3%82%AB%E3%83%97%E3%83%AA%E3%83%AB%E3%80%8C%E3%83%95%E3%82%A7%E3%83%AB%E3%82%BC%E3%83%B3%E3%80%8D_%E8%B2%A9%E5%A3%B2%E4%B8%AD%E6%AD%A2.pdf',
    },
    'JCRファーマ': {
        'https://med.kissei.co.jp/information/info122.pdf',
    },
    '阪大微生物病研究会': {
        'https://www.jpa-web.org/dcms_media/other/02_jebik-v-genteishukka_biken_260512.pdf',
    },
    '東光薬品工業': {
        'https://medical.nihon-generic.co.jp/uploadfiles/medicine/FELBI70_CHUUSHI_2507.pdf',
    },
    'サンド': {
        'https://www.jrs.or.jp/information/file/3393d536942bdd85d8d84103c5d69b6e1dc48fc4.pdf',
    },
    'ファイザー': {
        'https://www.j-circ.or.jp/cms/wp-content/uploads/2024/07/C03DA02.pdf',
        'https://www.j-endo.jp/uploads/files/news/20250617-12.pdf',
        'https://www.kansensho.or.jp/uploads/files/news/gakkai/gakkai_230721_2.pdf',
    },
    '武田薬品工業': {
        'https://www.city.funabashi.lg.jp/kodomo/kenkou/005/p076734_d/fil/R8_takeda.pdf',
        'https://www.jspho.org/files/oshirase/20260203b.pdf',
    },
}
SCOPES = {'product', 'package', 'seller_route_and_package'}
KINDS = {'discontinued', 'limited', 'stopped', 'resumed', 'resumption_planned', 'recall'}
PACKAGE_STATUSES = {'normal', 'limited', 'stopped', 'unconfirmed'}
PACKAGE_PLAN_EVENTS = {'stock_depletion', 'shipment_resumption', 'normal_shipment', 'discontinuation'}
FORMAL_YJ = re.compile(r'[0-9][0-9A-Z]{11}\Z')
ARCHIVE_FIELD = 'archived_from_csv_at'

def is_official_maker_source(maker, url):
    return url.scheme == 'https' and not (url.username or url.password) and bool(url.hostname) and (
        url.hostname == MAKER_HOSTS.get(maker)
        or url.hostname in MAKER_MANUAL_SOURCE_HOSTS.get(maker, ())
        or url.geturl() in MAKER_MANUAL_SOURCE_URLS.get(maker, ())
    )

def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')).lower())

def valid_date(value, month=False):
    if not isinstance(value, str): return False
    try:
        if month and re.fullmatch(r'\d{4}-\d{2}', value):
            return dt.date.fromisoformat(value + '-01').strftime('%Y-%m') == value
        return dt.date.fromisoformat(value).isoformat() == value
    except ValueError: return False

def archived_identity(record, yj, label, errors):
    """欠落品目の履歴は正式YJ・名称・明示された削除確認日が必要。"""
    archived = record.get(ARCHIVE_FIELD)
    if ARCHIVE_FIELD not in record:
        return False
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    if (not isinstance(yj, str) or not FORMAL_YJ.fullmatch(yj)
            or not valid_date(archived) or archived > today):
        errors.append(label + ': invalid archived CSV date/identity')
        return False
    return True

def validate_package_supply(package, label, errors):
    """包装の資料時点の状態と予定を分離する。予定日から状態を推測しない。"""
    if 'supply' not in package:
        return  # 既存の包装名・コードのみの案内はそのまま扱う。
    supply = package['supply']
    if not isinstance(supply, dict):
        errors.append(label + ': invalid package supply'); return
    status = supply.get('status')
    if not isinstance(status, str) or status not in PACKAGE_STATUSES:
        errors.append(label + ': invalid package supply status')
    elif status == 'unconfirmed':
        if 'status_text' in supply:
            errors.append(label + ': unconfirmed package cannot have status text')
    elif not isinstance(supply.get('status_text'), str) or not supply['status_text'].strip():
        errors.append(label + ': missing package source status text')
    plans = supply.get('plans')
    if not isinstance(plans, list):
        errors.append(label + ': invalid package plans')
    else:
        for plan in plans:
            if (not isinstance(plan, dict)
                    or not isinstance(plan.get('event'), str)
                    or plan['event'] not in PACKAGE_PLAN_EVENTS
                    or not isinstance(plan.get('timing'), str) or not plan['timing'].strip()):
                errors.append(label + ': invalid package plan')
    if 'note' in supply and (not isinstance(supply['note'], str) or not supply['note'].strip()):
        errors.append(label + ': invalid package supply note')

def validate(document, rows):
    errors = []
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or document['schema_version'] != 1 or not isinstance(document.get('notices'), list):
        return ['manufacturer_notices: invalid schema']
    by_yj = {r['YJコード']: r for r in rows}
    ids = set()
    for n in document['notices']:
        if not isinstance(n, dict):
            errors.append('notice must be an object'); continue
        label = str(n.get('id', '?'))
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', label) or label in ids: errors.append(label + ': invalid/duplicate id')
        ids.add(label)
        for field in ['maker', 'title', 'reason']:
            if not isinstance(n.get(field), str) or not n[field].strip(): errors.append(label + ': missing ' + field)
        if 'maker_supply_status' in n:
            status = n['maker_supply_status']
            if (not isinstance(status, dict) or any(
                key in status and (not isinstance(status[key], str) or not status[key].strip())
                for key in ('handling', 'volume')
            )):
                errors.append(label + ': invalid maker supply status')
        u = urlparse(str(n.get('url') or ''))
        if not is_official_maker_source(n.get('maker'), u): errors.append(label + ': unofficial URL or wrong publisher')
        if not re.fullmatch(r'[a-f0-9]{64}', str(n.get('sha256') or '')): errors.append(label + ': invalid source hash')
        if not isinstance(n.get('event_type'), str) or n['event_type'] not in KINDS: errors.append(label + ': invalid event type')
        if 'collection_mode' in n and n['collection_mode'] != 'manual': errors.append(label + ': invalid collection mode')
        for field in ['announced_at', 'verified_at']:
            if not valid_date(n.get(field), month=field == 'announced_at'): errors.append(label + ': invalid ' + field)
        # 本文年月やファイル名から公式一覧の掲載日を補わない。未確認は省略する。
        if 'listed_at' in n and not valid_date(n['listed_at']): errors.append(label + ': invalid listed_at')
        if valid_date(n.get('verified_at')) and n['verified_at'] > dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat(): errors.append(label + ': future verification')
        targets = n.get('targets')
        if not isinstance(targets, list) or not targets:
            errors.append(label + ': missing targets'); continue
        seen = set()
        for t in targets:
            if not isinstance(t, dict): errors.append(label + ': invalid target'); continue
            yj = t.get('yj_code')
            if not isinstance(yj, str) or not FORMAL_YJ.fullmatch(yj):
                errors.append(label + ': invalid target YJ'); continue
            if not isinstance(t.get('product_name'), str) or not t['product_name'].strip():
                errors.append(label + ': invalid target name')
            if t.get('maker') is not None and (not isinstance(t['maker'], str) or not t['maker'].strip()):
                errors.append(label + ': invalid target maker')
            row = by_yj.get(yj)
            if yj in seen: errors.append(label + ': repeated target')
            seen.add(yj)
            archived = archived_identity(t, yj, label, errors)
            if row is None:
                if not archived: errors.append(label + ': target identity mismatch ' + yj)
            elif norm(t.get('product_name')) != norm(row['商品名']):
                errors.append(label + ': target identity mismatch ' + yj)
            if row and not maker_is_listed_in_row(t.get('maker') or n.get('maker'), row):
                errors.append(label + ': target maker mismatch ' + yj)
            if not isinstance(t.get('scope'), str) or t['scope'] not in SCOPES: errors.append(label + ': invalid target scope')
            packages = t.get('packages')
            if not isinstance(packages, list) or (not packages and t.get('scope') != 'product') or any(not isinstance(p, dict) or not isinstance(p.get('package'), str) or not p['package'].strip() for p in packages):
                errors.append(label + ': missing package scope')
            else:
                for package in packages:
                    validate_package_supply(package, label, errors)
            if t.get('scope') == 'seller_route_and_package' and not t.get('seller'): errors.append(label + ': missing sales route')
        alternatives = n.get('alternatives')
        if not isinstance(alternatives, list): errors.append(label + ': invalid alternatives'); continue
        for g in alternatives:
            if not isinstance(g, dict) or not isinstance(g.get('products'), list): errors.append(label + ': invalid candidate group'); continue
            if 'source_url' in g and (g['source_url'] != n.get('url') or not g['products'] or not g.get('target_yj_codes')):
                errors.append(label + ': candidate source must match the notice and identify targeted products')
            selected = g.get('target_yj_codes') or []
            if not isinstance(selected, list) or any(not isinstance(yj, str) or not FORMAL_YJ.fullmatch(yj) for yj in selected):
                errors.append(label + ': invalid candidate group targets')
            elif not set(selected).issubset(seen):
                errors.append(label + ': candidate group outside targets')
            for p in g['products']:
                if not isinstance(p, dict) or not isinstance(p.get('name'), str) or not p['name'].strip(): errors.append(label + ': missing candidate name'); continue
                for field in ['maker', 'product_kind', 'source_class', 'manufacturer_candidate_scope', 'scope']:
                    if p.get(field) is not None and not isinstance(p[field], str):
                        errors.append(label + ': invalid candidate ' + field)
                yj = p.get('yj_code')
                if yj is not None and (not isinstance(yj, str) or not FORMAL_YJ.fullmatch(yj)):
                    errors.append(label + ': invalid candidate YJ'); continue
                archived = archived_identity(p, yj, label, errors)
                if yj:
                    row = by_yj.get(yj)
                    if row is None:
                        if not archived: errors.append(label + ': candidate identity mismatch ' + yj)
                    elif norm(p['name']) != norm(row['商品名']):
                        errors.append(label + ': candidate identity mismatch ' + yj)
                    if p.get('maker') is not None and (not isinstance(p['maker'], str) or not p['maker'].strip()
                            or (row and not maker_is_listed_in_row(p['maker'], row))):
                        errors.append(label + ': candidate maker mismatch ' + yj)
                if p.get('product_kind') == 'medical_device' and yj: errors.append(label + ': device cannot have medicine YJ')
            if not isinstance(g.get('cautions', []), list) or any(not isinstance(s, str) for s in g.get('cautions', [])): errors.append(label + ': invalid group cautions')
        if not isinstance(n.get('cautions'), list) or any(not isinstance(s, str) for s in n['cautions']): errors.append(label + ': invalid cautions')
    return errors

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, default=Path('.'))
    args = p.parse_args()
    rows = list(csv.DictReader((args.base / 'drugs_app_ready.csv').open(encoding='utf-8-sig')))
    errors = validate(json.loads((args.base / 'manufacturer_notices.json').read_text(encoding='utf-8')), rows)
    if errors: raise SystemExit('\n'.join(errors))
    print('OK: verified manufacturer notices')

if __name__ == '__main__': main()
