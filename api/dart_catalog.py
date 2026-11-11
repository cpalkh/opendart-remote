"""
OpenDART API 카탈로그 (개발가이드 기준, 2026-09 확인)

각 엔드포인트: key(엔드포인트명), group, 한글명, 호출 유형, 응답 필드 한글 라벨.
호출 유형
  corp      : corp_code 만
  periodic  : corp_code, bsns_year, reprt_code  (정기보고서 계열)
  event     : corp_code, bgn_de, end_de        (주요사항보고서 / 증권신고서)
  special   : 개별 처리
"""

GROUPS = {
    "DS001": "공시정보",
    "DS002": "정기보고서 주요정보",
    "DS003": "정기보고서 재무정보",
    "DS004": "지분공시 종합정보",
    "DS005": "주요사항보고서 주요정보",
    "DS006": "증권신고서 주요정보",
}

# 여러 API에 공통으로 나오는 필드
COMMON_LABELS = {
    "rcept_no": "접수번호", "rcept_dt": "접수일자", "corp_cls": "법인구분", "corp_code": "고유번호",
    "corp_name": "회사명", "stlm_dt": "결산기준일", "rm": "비고", "se": "구분", "stock_knd": "주식종류",
    "bsns_year": "사업연도", "fscl_year": "사업연도",
    "bddd": "이사회결의일(결정일)", "od_a_at_t": "사외이사 참석(명)", "od_a_at_b": "사외이사 불참(명)",
    "adt_a_atn": "감사(감사위원) 참석여부", "popt_ctr_atn": "풋옵션 등 계약 체결여부", "popt_ctr_cn": "풋옵션 계약내용",
    "rs_sm_atn": "증권신고서 제출대상 여부", "ex_sm_r": "증권신고서 제출 면제 사유",
    "ftc_stt_atn": "공정위 신고대상 여부", "cfd": "확인일자",
    "exevl_atn": "외부평가 여부", "exevl_bs_rs": "외부평가 근거 및 사유", "exevl_intn": "외부평가기관",
    "exevl_pd": "외부평가 기간", "exevl_op": "외부평가 의견",
    "aprskh_exrq": "주식매수청구권(행사요건)", "aprskh_plnprc": "주식매수청구권(매수예정가격)",
    "aprskh_ex_pc_mth_pd_pl": "주식매수청구권(행사절차·방법·기간·장소)",
    "aprskh_pym_plpd_mth": "주식매수청구권(지급예정시기·방법)", "aprskh_lmt": "주식매수청구권(제한 관련 내용)",
    "aprskh_ctref": "주식매수청구권(계약에 미치는 효력)",
    "dlptn_cmpnm": "거래상대방(회사명)", "dlptn_cpt": "거래상대방(자본금)", "dlptn_mbsn": "거래상대방(주요사업)",
    "dlptn_hoadd": "거래상대방(본점소재지)", "dlptn_rl_cmpn": "거래상대방(회사와의 관계)", "dl_pym": "거래대금지급",
    "gmtsck_spd_atn": "주주총회 특별결의 여부", "gmtsck_prd": "주주총회 예정일",
    "bdlst_atn": "우회상장 해당 여부", "otcpr_bdlst_sf_atn": "타법인 우회상장 요건 충족여부",
    "n6m_tpai_plann": "향후 6월내 제3자배정 증자 계획",
    "cs_iv_bk": "위탁투자중개업자",
    "fdpp_fclt": "자금목적(시설자금)", "fdpp_bsninh": "자금목적(영업양수자금)", "fdpp_op": "자금목적(운영자금)",
    "fdpp_dtrp": "자금목적(채무상환자금)", "fdpp_ocsa": "자금목적(타법인증권취득자금)", "fdpp_etc": "자금목적(기타자금)",
    "ssl_at": "공매도 해당여부", "ssl_bgd": "공매도 시작일", "ssl_edd": "공매도 종료일",
    "remndr_exprtn1": "잔여만기", "remndr_exprtn2": "잔여만기(구분)", "sm": "합계",
    "nm": "성명", "ofcps": "직위", "nmpr": "인원수",
    "mendng_totamt": "보수총액", "mendng_totamt_ct_incls_mendng": "보수총액 비포함 보수",
    "stk_bsd_pd_mendng_totamt": "주식기준보상 지급액", "stk_bsd_pd_mendng_totamt_knd": "주식기준보상 종류",
    "stk_bsd_pd_mendng_totamt_qty": "주식기준보상 수량", "stk_bsd_pd_mendng_totamt_amt": "주식기준보상 금액",
    "stk_opt_exrcsbl_qty": "스톡옵션 행사가능수량", "stk_opt_unexrcsbl_qty": "스톡옵션 행사불가수량",
    "stk_opt_exrc_pr": "스톡옵션 행사가격", "stk_opt_rmn_blce": "스톡옵션 잔여금액",
    "othr_stk_bsd_cmpn_unpyd_qty": "기타 주식기준보상 미지급수량", "othr_stk_bsd_cmpn_mkt_vl": "기타 주식기준보상 시장가치",
    # 사채 공통
    "bd_tm": "사채 회차", "bd_knd": "사채 종류", "bd_fta": "권면총액(원)", "atcsc_rmislmt": "정관상 잔여 발행한도(원)",
    "ovis_fta": "해외발행 권면총액", "ovis_fta_crn": "해외발행 통화", "ovis_ster": "해외발행 기준환율",
    "ovis_isar": "해외발행 지역", "ovis_mktnm": "해외상장 시장", "bd_intr_ex": "표면이자율(%)",
    "bd_intr_sf": "만기이자율(%)", "bd_mtd": "사채만기일", "bdis_mthn": "사채발행방법", "abmg": "합병 관련 사항",
    "sbd": "청약일", "pymd": "납입일", "rpmcmp": "대표주관회사", "grint": "보증기관",
    "ovis_ltdtl": "해외발행 연계 대차거래 내역",
    # 자기주식 보유현황 공통
    "aq_wtn_div_ostk": "기보유 자기주식-배당가능이익 내 취득(보통)", "aq_wtn_div_ostk_rt": "…비율(%)",
    "aq_wtn_div_estk": "기보유 자기주식-배당가능이익 내 취득(기타)", "aq_wtn_div_estk_rt": "…비율(%) ",
    "eaq_ostk": "기보유 자기주식-기타취득(보통)", "eaq_ostk_rt": "기타취득 비율(%)(보통)",
    "eaq_estk": "기보유 자기주식-기타취득(기타)", "eaq_estk_rt": "기타취득 비율(%)(기타)",
    # 증권신고서 공통
    "title": "그룹", "stn": "형태", "ctrd": "계약일", "gmtsck_shddstd": "주총 주주확정일", "ap_gmtsck": "승인 주주총회일",
    "aprskh_pd_bgd": "주식매수청구 기간(시작)", "aprskh_pd_edd": "주식매수청구 기간(종료)",
    "aprskh_prc": "주식매수청구가격(회사제시)", "mgdt_etc": "합병(분할)기일 등", "rt_vl": "비율 또는 가액",
    "exevl_int": "외부평가기관", "grtmn_etc": "지급 교부금 등", "rpt_rcpn": "주요사항보고서 접수번호",
    "kndn": "종류", "cnt": "수량", "fv": "액면가액", "slprc": "모집(매출)가액", "slta": "모집(매출)총액",
    "cmpnm": "회사명", "sen": "구분", "tast": "총자산", "cpt": "자본금",
    "isstk_knd": "발행주식 종류", "isstk_cnt": "발행주식수",
    "sband": "청약공고일", "asand": "배정공고일", "asstd": "배정기준일",
    "exstk": "신주인수권 행사대상증권", "exprc": "신주인수권 행사가격", "expd": "신주인수권 행사기간",
    "stksen": "증권의 종류", "stkcnt": "증권수량", "slmthn": "모집(매출)방법",
    "actsen": "인수인 구분", "actnmn": "인수인명", "udtcnt": "인수수량", "udtamt": "인수금액", "udtprc": "인수대가",
    "udtmth": "인수방법", "amt": "금액", "hdr": "보유자", "rl_cmp": "회사와의 관계",
    "bfsl_hdstk": "매출전 보유증권수", "slstk": "매출증권수", "atsl_hdstk": "매출후 보유증권수",
    "grtrs": "부여사유", "exavivr": "행사가능 투자자", "grtcnt": "부여수량",
}

# (key, group, 한글명, 유형, 검색 별칭들, 엔드포인트 고유 라벨)
_E = []


def _add(key, group, name, kind, aliases=(), labels=None):
    _E.append({"key": key, "group": group, "name": name, "kind": kind,
               "aliases": list(aliases), "labels": labels or {}})


# ---------------- DS001 공시정보 ----------------
_add("list", "DS001", "공시검색", "special")
_add("company", "DS001", "기업개황", "corp")
_add("document", "DS001", "공시서류원본파일", "special")
_add("corpCode", "DS001", "고유번호", "special")

# ---------------- DS002 정기보고서 주요정보 ----------------
_add("stockTotqySttus", "DS002", "주식의 총수 현황", "periodic", ["주식총수", "발행주식", "유통주식", "자기주식수"], {
    "isu_stock_totqy": "발행할 주식의 총수", "now_to_isu_stock_totqy": "현재까지 발행한 주식의 총수",
    "now_to_dcrs_stock_totqy": "현재까지 감소한 주식의 총수", "redc": "감자", "profit_incnr": "이익소각",
    "rdmstk_repy": "상환주식의 상환", "etc": "기타", "istc_totqy": "발행주식의 총수", "tesstk_co": "자기주식수",
    "distb_stock_co": "유통주식수"})
_add("tesstkAcqsDspsSttus", "DS002", "자기주식 취득 및 처분 현황", "periodic", ["자기주식", "자사주"], {
    "acqs_mth1": "취득방법 대분류", "acqs_mth2": "취득방법 중분류", "acqs_mth3": "취득방법 소분류",
    "bsis_qy": "기초 수량", "change_qy_acqs": "취득", "change_qy_dsps": "처분", "change_qy_incnr": "소각",
    "trmend_qy": "기말 수량"})
_add("alotMatter", "DS002", "배당에 관한 사항", "periodic", ["배당"], {
    "thstrm": "당기", "frmtrm": "전기", "lwfr": "전전기"})
_add("irdsSttus", "DS002", "증자(감자) 현황", "periodic", ["증자", "감자"], {
    "isu_dcrs_de": "발행(감소)일자", "isu_dcrs_stle": "발행(감소) 형태", "isu_dcrs_stock_knd": "주식 종류",
    "isu_dcrs_qy": "수량", "isu_dcrs_mstvdv_fval_amount": "주당 액면가액", "isu_dcrs_mstvdv_amount": "주당 가액"})
_add("detScritsIsuAcmslt", "DS002", "채무증권 발행실적", "periodic", ["채무증권", "사채발행실적"], {
    "isu_cmpny": "발행회사", "scrits_knd_nm": "증권종류", "isu_mth_nm": "발행방법", "isu_de": "발행일자",
    "facvalu_totamt": "권면총액", "intrt": "이자율", "evl_grad_instt": "평가등급(평가기관)", "mtd": "만기일",
    "repy_at": "상환여부", "mngt_cmpny": "주관회사"})
_add("entrprsBilScritsNrdmpBlce", "DS002", "기업어음증권 미상환 잔액", "periodic", ["기업어음", "CP"], {
    "de10_below": "10일 이하", "de10_excess_de30_below": "10~30일", "de30_excess_de90_below": "30~90일",
    "de90_excess_de180_below": "90~180일", "de180_excess_yy1_below": "180일~1년", "yy1_excess_yy2_below": "1~2년",
    "yy2_excess_yy3_below": "2~3년", "yy3_excess": "3년 초과"})
_add("srtpdPsndbtNrdmpBlce", "DS002", "단기사채 미상환 잔액", "periodic", ["단기사채"], {
    "de10_below": "10일 이하", "de10_excess_de30_below": "10~30일", "de30_excess_de90_below": "30~90일",
    "de90_excess_de180_below": "90~180일", "de180_excess_yy1_below": "180일~1년", "isu_lmt": "발행 한도",
    "remndr_lmt": "잔여 한도"})
_add("cprndNrdmpBlce", "DS002", "회사채 미상환 잔액", "periodic", ["회사채"], {
    "yy1_below": "1년 이하", "yy1_excess_yy2_below": "1~2년", "yy2_excess_yy3_below": "2~3년",
    "yy3_excess_yy4_below": "3~4년", "yy4_excess_yy5_below": "4~5년", "yy5_excess_yy10_below": "5~10년",
    "yy10_excess": "10년 초과"})
_add("newCaplScritsNrdmpBlce", "DS002", "신종자본증권 미상환 잔액", "periodic", ["신종자본증권", "영구채"], {
    "yy1_below": "1년 이하", "yy1_excess_yy5_below": "1~5년", "yy5_excess_yy10_below": "5~10년",
    "yy10_excess_yy15_below": "10~15년", "yy15_excess_yy20_below": "15~20년", "yy20_excess_yy30_below": "20~30년",
    "yy30_excess": "30년 초과"})
_add("cndlCaplScritsNrdmpBlce", "DS002", "조건부 자본증권 미상환 잔액", "periodic", ["조건부자본증권", "코코본드"], {
    "yy1_below": "1년 이하", "yy1_excess_yy2_below": "1~2년", "yy2_excess_yy3_below": "2~3년",
    "yy3_excess_yy4_below": "3~4년", "yy4_excess_yy5_below": "4~5년", "yy5_excess_yy10_below": "5~10년",
    "yy10_excess_yy20_below": "10~20년", "yy20_excess_yy30_below": "20~30년", "yy30_excess": "30년 초과"})
_add("pssrpCptalUseDtls", "DS002", "공모자금의 사용내역", "periodic", ["공모자금"], {
    "se_nm": "구분", "tm": "회차", "pay_de": "납입일", "pay_amount": "납입금액",
    "on_dclrt_cptal_use_plan": "신고서상 자금사용 계획", "real_cptal_use_sttus": "실제 자금사용 현황",
    "rs_cptal_use_plan_useprps": "계획 사용용도", "rs_cptal_use_plan_prcure_amount": "계획 조달금액",
    "real_cptal_use_dtls_cn": "실제 사용 내용", "real_cptal_use_dtls_amount": "실제 사용 금액",
    "dffrnc_occrrnc_resn": "차이발생 사유"})
_add("prvsrpCptalUseDtls", "DS002", "사모자금의 사용내역", "periodic", ["사모자금"], {
    "se_nm": "구분", "tm": "회차", "pay_de": "납입일", "pay_amount": "납입금액", "cptal_use_plan": "자금사용 계획",
    "real_cptal_use_sttus": "실제 자금사용 현황", "mtrpt_cptal_use_plan_useprps": "계획 사용용도",
    "mtrpt_cptal_use_plan_prcure_amount": "계획 조달금액", "real_cptal_use_dtls_cn": "실제 사용 내용",
    "real_cptal_use_dtls_amount": "실제 사용 금액", "dffrnc_occrrnc_resn": "차이발생 사유"})
_add("accnutAdtorNmNdAdtOpinion", "DS002", "회계감사인의 명칭 및 감사의견", "periodic", ["감사의견", "감사인", "회계감사"], {
    "adtor": "감사인", "adt_opinion": "감사의견", "adt_reprt_spcmnt_matter": "감사보고서 특기사항",
    "emphs_matter": "강조사항 등", "core_adt_matter": "핵심감사사항"})
_add("adtServcCnclsSttus", "DS002", "감사용역체결현황", "periodic", ["감사용역", "감사보수"], {
    "adtor": "감사인", "cn": "내용", "mendng": "보수", "tot_reqre_time": "총소요시간",
    "adt_cntrct_dtls_mendng": "감사계약 보수", "adt_cntrct_dtls_time": "감사계약 시간",
    "real_exc_dtls_mendng": "실제수행 보수", "real_exc_dtls_time": "실제수행 시간"})
_add("accnutAdtorNonAdtServcCnclsSttus", "DS002", "회계감사인과의 비감사용역 계약체결 현황", "periodic", ["비감사용역"], {
    "cntrct_cncls_de": "계약체결일", "servc_cn": "용역내용", "servc_exc_pd": "용역수행기간", "servc_mendng": "용역보수"})
_add("outcmpnyDrctrNdChangeSttus", "DS002", "사외이사 및 그 변동현황", "periodic", ["사외이사"], {
    "drctr_co": "이사 수", "otcmp_drctr_co": "사외이사 수", "apnt": "선임", "rlsofc": "해임", "mdstrm_resig": "중도퇴임"})
_add("hyslrSttus", "DS002", "최대주주 현황", "periodic", ["최대주주"], {
    "relate": "관계", "bsis_posesn_stock_co": "기초 주식수", "bsis_posesn_stock_qota_rt": "기초 지분율",
    "trmend_posesn_stock_co": "기말 주식수", "trmend_posesn_stock_qota_rt": "기말 지분율"})
_add("hyslrChgSttus", "DS002", "최대주주 변동현황", "periodic", ["최대주주변동"], {
    "change_on": "변동일", "mxmm_shrholdr_nm": "최대주주명", "posesn_stock_co": "소유주식수", "qota_rt": "지분율",
    "change_cause": "변동원인"})
_add("mrhlSttus", "DS002", "소액주주 현황", "periodic", ["소액주주"], {
    "shrholdr_co": "주주수", "shrholdr_tot_co": "전체 주주수", "shrholdr_rate": "주주 비율",
    "hold_stock_co": "보유 주식수", "stock_tot_co": "총발행 주식수", "hold_stock_rate": "보유 주식 비율"})
_add("exctvSttus", "DS002", "임원 현황", "periodic", ["임원"], {
    "sexdstn": "성별", "birth_ym": "출생년월", "rgist_exctv_at": "등기임원 여부", "fte_at": "상근 여부",
    "chrg_job": "담당업무", "main_career": "주요경력", "mxmm_shrholdr_relate": "최대주주 관계",
    "hffc_pd": "재직기간", "tenure_end_on": "임기만료일"})
_add("empSttus", "DS002", "직원 현황", "periodic", ["직원", "급여", "근속"], {
    "fo_bbm": "사업부문", "sexdstn": "성별", "reform_bfe_emp_co_rgllbr": "(개정전)정규직",
    "reform_bfe_emp_co_cnttk": "(개정전)계약직", "reform_bfe_emp_co_etc": "(개정전)기타", "rgllbr_co": "정규직 수",
    "rgllbr_abacpt_labrr_co": "정규직 단시간", "cnttk_co": "계약직 수", "cnttk_abacpt_labrr_co": "계약직 단시간",
    "avrg_cnwk_sdytrn": "평균근속연수", "fyer_salary_totamt": "연간급여총액", "jan_salary_am": "1인평균급여액"})
_add("unrstExctvMendngSttus", "DS002", "미등기임원 보수현황", "periodic", ["미등기임원보수"], {
    "fyer_salary_totamt": "연간급여총액", "jan_salary_am": "1인평균급여액"})
_add("drctrAdtAllMendngSttusGmtsckConfmAmount", "DS002", "이사·감사 전체 보수현황(주총 승인금액)", "periodic",
     ["임원보수승인", "주총승인보수"], {"gmtsck_confm_amount": "주주총회 승인금액"})
_add("hmvAuditAllSttus", "DS002", "이사·감사 전체 보수현황(지급금액-전체)", "periodic", ["임원전체보수"], {
    "jan_avrg_mendng_am": "1인 평균보수액"})
_add("drctrAdtAllMendngSttusMendngPymntamtTyCl", "DS002", "이사·감사 전체 보수현황(지급금액-유형별)", "periodic",
     ["임원보수유형"], {"pymnt_totamt": "보수총액", "psn1_avrg_pymntamt": "1인당 평균보수액"})
_add("hmvAuditIndvdlBySttus", "DS002", "이사·감사 개인별 보수현황(5억 이상)", "periodic", ["임원개인보수(구)"])
_add("hmvAuditIndvdlBySttusV2", "DS002", "이사·감사 개인별 보수현황(5억 이상) Ver2.0 (2026.5~)", "periodic",
     ["임원개인보수", "개인별보수", "5억"])
_add("indvdlByPay", "DS002", "개인별 보수지급 금액(5억 이상 상위5인)", "periodic", ["상위5인(구)"])
_add("indvdlByPayV2", "DS002", "개인별 보수지급 금액(5억 이상 상위5인) Ver2.0 (2026.5~)", "periodic",
     ["상위5인", "고액연봉", "보수상위"])
_add("otrCprInvstmntSttus", "DS002", "타법인 출자현황", "periodic", ["타법인출자", "출자"], {
    "inv_prm": "법인명", "frst_acqs_de": "최초취득일", "invstmnt_purps": "출자목적", "frst_acqs_amount": "최초취득금액",
    "bsis_blce_qy": "기초 수량", "bsis_blce_qota_rt": "기초 지분율", "bsis_blce_acntbk_amount": "기초 장부가액",
    "incrs_dcrs_acqs_dsps_qy": "증감 수량", "incrs_dcrs_acqs_dsps_amount": "증감 금액",
    "incrs_dcrs_evl_lstmn": "평가손익", "trmend_blce_qy": "기말 수량", "trmend_blce_qota_rt": "기말 지분율",
    "trmend_blce_acntbk_amount": "기말 장부가액", "recent_bsns_year_fnnr_sttus_tot_assets": "피출자사 총자산",
    "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "피출자사 당기순이익"})

# ---------------- DS003 재무정보 ----------------
_add("fnlttSinglAcnt", "DS003", "단일회사 주요계정", "periodic")
_add("fnlttMultiAcnt", "DS003", "다중회사 주요계정", "periodic")
_add("fnlttXbrl", "DS003", "재무제표 원본파일(XBRL)", "special")
_add("fnlttSinglAcntAll", "DS003", "단일회사 전체 재무제표", "special")
_add("xbrlTaxonomy", "DS003", "XBRL 택사노미 재무제표양식", "special")
_add("fnlttSinglIndx", "DS003", "단일회사 주요 재무지표", "special")
_add("fnlttCmpnyIndx", "DS003", "다중회사 주요 재무지표", "special")

# ---------------- DS004 지분공시 ----------------
_add("majorstock", "DS004", "대량보유 상황보고", "corp", ["5%", "대량보유"], {
    "report_tp": "보고구분", "repror": "대표보고자", "stkqy": "보유주식수", "stkqy_irds": "보유주식 증감",
    "stkrt": "보유비율", "stkrt_irds": "보유비율 증감", "ctr_stkqy": "주요체결 주식수", "ctr_stkrt": "주요체결 보유비율",
    "report_resn": "보고사유"})
_add("elestock", "DS004", "임원·주요주주 소유보고", "corp", ["임원지분", "내부자"], {
    "repror": "보고자", "isu_exctv_rgist_at": "임원 등기여부", "isu_exctv_ofcps": "임원 직위",
    "isu_main_shrholdr": "주요주주", "sp_stock_lmp_cnt": "소유 주식수", "sp_stock_lmp_irds_cnt": "소유 증감",
    "sp_stock_lmp_rate": "소유 비율", "sp_stock_lmp_irds_rate": "소유비율 증감"})

# ---------------- DS005 주요사항보고서 ----------------
_DV = {
    "dv_mth": "분할방법", "dv_impef": "분할의 중요영향 및 효과", "dv_rt": "분할비율",
    "dv_trfbsnprt_cn": "분할로 이전할 사업 및 재산", "atdv_excmp_cmpnm": "존속회사명",
    "atdvfdtl_tast": "존속회사 자산총계", "atdvfdtl_tdbt": "존속회사 부채총계", "atdvfdtl_teqt": "존속회사 자본총계",
    "atdvfdtl_cpt": "존속회사 자본금", "atdvfdtl_std": "존속회사 재무 기준일", "atdv_excmp_exbsn_rsl": "존속사업부문 최근 매출액",
    "atdv_excmp_mbsn": "존속회사 주요사업", "atdv_excmp_atdv_lstmn_atn": "존속회사 상장유지 여부",
    "dvfcmp_cmpnm": "분할설립회사명", "ffdtl_tast": "설립회사 자산총계", "ffdtl_tdbt": "설립회사 부채총계",
    "ffdtl_teqt": "설립회사 자본총계", "ffdtl_cpt": "설립회사 자본금", "ffdtl_std": "설립회사 재무 기준일",
    "dvfcmp_nbsn_rsl": "신설사업부문 최근 매출액", "dvfcmp_mbsn": "설립회사 주요사업", "dvfcmp_rlst_atn": "설립회사 재상장신청 여부",
    "dvfcmp_atdv_lstmn_at": "설립회사 상장유지 여부",
    "abcr_crrt": "감자비율(%)", "abcr_osprpd_bgd": "구주권 제출(시작)", "abcr_osprpd_edd": "구주권 제출(종료)",
    "abcr_trspprpd_bgd": "매매정지(시작)", "abcr_trspprpd_edd": "매매정지(종료)", "abcr_nstkascnd": "신주배정조건",
    "abcr_shstkcnt_rt_at_rs": "주식수 비례여부 및 사유", "abcr_nstkasstd": "신주배정기준일", "abcr_nstkdlprd": "신주권교부예정일",
    "abcr_nstklstprd": "신주 상장예정일", "cdobprpd_bgd": "채권자 이의제출(시작)", "cdobprpd_edd": "채권자 이의제출(종료)",
    "dvdt": "분할기일", "dvrgsprd": "분할등기 예정일",
}
_MG = {
    "mg_mth": "합병방법", "mg_stn": "합병형태", "mg_pp": "합병목적", "mg_rt": "합병비율", "mg_rt_bs": "합병비율 산출근거",
    "mgnstk_ostk_cnt": "합병신주(보통)", "mgnstk_cstk_cnt": "합병신주(종류)", "mgptncmp_cmpnm": "합병상대회사",
    "mgptncmp_mbsn": "상대회사 주요사업", "mgptncmp_rl_cmpn": "상대회사와의 관계", "rbsnfdtl_tast": "상대회사 자산총계",
    "rbsnfdtl_tdbt": "상대회사 부채총계", "rbsnfdtl_teqt": "상대회사 자본총계", "rbsnfdtl_cpt": "상대회사 자본금",
    "rbsnfdtl_sl": "상대회사 매출액", "rbsnfdtl_nic": "상대회사 당기순이익", "eadtat_intn": "상대회사 감사인",
    "eadtat_op": "상대회사 감사의견", "nmgcmp_cmpnm": "신설합병회사", "ffdtl_tast": "신설회사 자산총계",
    "ffdtl_tdbt": "신설회사 부채총계", "ffdtl_teqt": "신설회사 자본총계", "ffdtl_cpt": "신설회사 자본금",
    "ffdtl_std": "신설회사 재무 기준일", "nmgcmp_nbsn_rsl": "신설사업부문 매출액", "nmgcmp_mbsn": "신설회사 주요사업",
    "nmgcmp_rlst_atn": "신설회사 재상장신청 여부", "nmgcmp_cpt": "신설회사 자본금",
    "mgsc_mgctrd": "합병계약일", "mgsc_shddstd": "주주확정기준일", "mgsc_shclspd_bgd": "명부폐쇄(시작)",
    "mgsc_shclspd_edd": "명부폐쇄(종료)", "mgsc_mgop_rcpd_bgd": "반대의사통지(시작)", "mgsc_mgop_rcpd_edd": "반대의사통지(종료)",
    "mgsc_gmtsck_prd": "주주총회 예정일", "mgsc_aprskh_expd_bgd": "매수청구(시작)", "mgsc_aprskh_expd_edd": "매수청구(종료)",
    "mgsc_osprpd_bgd": "구주권제출(시작)", "mgsc_osprpd_edd": "구주권제출(종료)", "mgsc_trspprpd_bgd": "매매정지(시작)",
    "mgsc_trspprpd_edd": "매매정지(종료)", "mgsc_cdobprpd_bgd": "채권자이의(시작)", "mgsc_cdobprpd_edd": "채권자이의(종료)",
    "mgsc_mgdt": "합병기일", "mgsc_ergmd": "종료보고 총회일", "mgsc_mgrgsprd": "합병등기 예정일",
    "mgsc_nstkdlprd": "신주권교부 예정일", "mgsc_nstklstprd": "신주 상장예정일",
}
_DVMG = dict(_DV)
_DVMG.update(_MG)
_DVMG.update({
    "dvmg_mth": "분할합병 방법", "dvmg_impef": "분할합병의 중요영향 및 효과", "dvmgnstk_ostk_cnt": "분할합병신주(보통)",
    "dvmgnstk_cstk_cnt": "분할합병신주(종류)", "dvmg_rt": "분할합병비율", "dvmg_rt_bs": "분할합병비율 산출근거",
    "dvmgsc_dvmgctrd": "분할합병계약일", "dvmgsc_shddstd": "주주확정기준일", "dvmgsc_shclspd_bgd": "명부폐쇄(시작)",
    "dvmgsc_shclspd_edd": "명부폐쇄(종료)", "dvmgsc_dvmgop_rcpd_bgd": "반대의사통지(시작)",
    "dvmgsc_dvmgop_rcpd_edd": "반대의사통지(종료)", "dvmgsc_gmtsck_prd": "주주총회 예정일",
    "dvmgsc_aprskh_expd_bgd": "매수청구(시작)", "dvmgsc_aprskh_expd_edd": "매수청구(종료)",
    "dvmgsc_cdobprpd_bgd": "채권자이의(시작)", "dvmgsc_cdobprpd_edd": "채권자이의(종료)", "dvmgsc_dvmgdt": "분할합병기일",
    "dvmgsc_ergmd": "종료보고 총회일", "dvmgsc_dvmgrgsprd": "분할합병등기 예정일",
})
_NSTK = {
    "nstk_ostk_cnt": "신주(보통,주)", "nstk_estk_cnt": "신주(기타,주)", "fv_ps": "1주당 액면가(원)",
    "bfic_tisstk_ostk": "증자전 발행주식(보통)", "bfic_tisstk_estk": "증자전 발행주식(기타)",
    "nstk_asstd": "신주배정기준일", "nstk_ascnt_ps_ostk": "1주당 신주배정(보통)", "nstk_ascnt_ps_estk": "1주당 신주배정(기타)",
    "nstk_dividrk": "신주 배당기산일", "nstk_dlprd": "신주권교부예정일", "nstk_lstprd": "신주 상장예정일", "ic_mthn": "증자방식",
}
_PIFRIC = {}
for _k, _v in _NSTK.items():
    _PIFRIC["piic_" + _k] = "유상-" + _v
    _PIFRIC["fric_" + _k] = "무상-" + _v
for _k in ("fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"):
    _PIFRIC["piic_" + _k] = "유상-" + COMMON_LABELS[_k]
_PIFRIC.update({"fric_bddd": "무상-이사회결의일", "fric_od_a_at_t": "무상-사외이사 참석",
                "fric_od_a_at_b": "무상-사외이사 불참", "fric_adt_a_atn": "무상-감사 참석여부"})
_ASSET_TRADE = {
    "ast_sen": "자산구분", "ast_nm": "자산명", "inhdtl_inhprc": "양수금액(원)", "inhdtl_tast": "자산총액(원)",
    "inhdtl_tast_vs": "자산총액대비(%)", "trfdtl_trfprc": "양도금액(원)", "trfdtl_tast": "자산총액(원)",
    "trfdtl_tast_vs": "자산총액대비(%)", "inh_pp": "양수목적", "inh_af": "양수영향", "trf_pp": "양도목적",
    "trf_af": "양도영향", "inh_prd_ctr_cnsd": "계약체결일", "inh_prd_inh_std": "양수기준일", "inh_prd_rgs_prd": "등기예정일",
    "trf_prd_ctr_cnsd": "계약체결일", "trf_prd_trf_std": "양도기준일", "trf_prd_rgs_prd": "등기예정일",
}
_BSN = {
    "inh_bsn": "양수영업", "inh_bsn_mc": "양수영업 주요내용", "inh_prc": "양수가액(원)", "absn_inh_atn": "영업전부 양수 여부",
    "trf_bsn": "양도영업", "trf_bsn_mc": "양도영업 주요내용", "trf_prc": "양도가액(원)",
    "ast_inh_bsn": "자산액(대상부문)", "ast_trf_bsn": "자산액(대상부문)", "ast_cmp_all": "자산액(당사전체)", "ast_rt": "자산 비중(%)",
    "sl_inh_bsn": "매출액(대상부문)", "sl_trf_bsn": "매출액(대상부문)", "sl_cmp_all": "매출액(당사전체)", "sl_rt": "매출 비중(%)",
    "dbt_inh_bsn": "부채액(대상부문)", "dbt_cmp_all": "부채액(당사전체)", "dbt_rt": "부채 비중(%)",
    "inh_pp": "양수목적", "inh_af": "양수영향", "trf_pp": "양도목적", "trf_af": "양도영향",
    "inh_prd_ctr_cnsd": "계약체결일", "inh_prd_inh_std": "양수기준일", "trf_prd_ctr_cnsd": "계약체결일",
    "trf_prd_trf_std": "양도기준일", "inh_pym": "양수대금지급", "trf_pym": "양도대금지급",
}
_OTC = {
    "iscmp_cmpnm": "발행회사", "iscmp_nt": "발행회사 국적", "iscmp_rp": "발행회사 대표자", "iscmp_cpt": "발행회사 자본금",
    "iscmp_rl_cmpn": "발행회사와 관계", "iscmp_tisstk": "발행회사 발행주식총수", "iscmp_mbsn": "발행회사 주요사업",
    "l6m_tpa_nstkaq_atn": "최근6월 제3자배정 신주취득 여부",
    "inhdtl_stkcnt": "양수주식수", "inhdtl_inhprc": "양수금액(원)", "inhdtl_tast": "총자산(원)", "inhdtl_tast_vs": "총자산대비(%)",
    "inhdtl_ecpt": "자기자본(원)", "inhdtl_ecpt_vs": "자기자본대비(%)", "atinh_owstkcnt": "양수후 소유주식수", "atinh_eqrt": "양수후 지분율(%)",
    "trfdtl_stkcnt": "양도주식수", "trfdtl_trfprc": "양도금액(원)", "trfdtl_tast": "총자산(원)", "trfdtl_tast_vs": "총자산대비(%)",
    "trfdtl_ecpt": "자기자본(원)", "trfdtl_ecpt_vs": "자기자본대비(%)", "attrf_owstkcnt": "양도후 소유주식수", "attrf_eqrt": "양도후 지분율(%)",
    "inh_pp": "양수목적", "inh_prd": "양수예정일", "trf_pp": "양도목적", "trf_prd": "양도예정일",
    "iscmp_bdlst_sf_atn": "발행회사 우회상장 요건 충족여부",
}
_STKRTBD = dict(_OTC)
_STKRTBD.update({
    "stkrtbd_kndn": "사채권 종류", "tm": "회차", "knd": "종류", "aqd": "취득일자", "bdiscmp_cmpnm": "사채 발행회사",
    "bdiscmp_nt": "발행회사 국적", "bdiscmp_rp": "발행회사 대표자", "bdiscmp_cpt": "발행회사 자본금",
    "bdiscmp_rl_cmpn": "발행회사와 관계", "bdiscmp_tisstk": "발행회사 발행주식총수", "bdiscmp_mbsn": "발행회사 주요사업",
    "inhdtl_bd_fta": "양수 권면총액(원)", "trfdtl_bd_fta": "양도 권면총액(원)",
})
_TSSTK = {
    "aqpln_stk_ostk": "취득예정주식(보통)", "aqpln_stk_estk": "취득예정주식(기타)", "aqpln_prc_ostk": "취득예정금액(보통,원)",
    "aqpln_prc_estk": "취득예정금액(기타,원)", "aqexpd_bgd": "취득기간(시작)", "aqexpd_edd": "취득기간(종료)",
    "hdexpd_bgd": "보유기간(시작)", "hdexpd_edd": "보유기간(종료)", "aq_pp": "취득목적", "aq_mth": "취득방법",
    "aq_dd": "취득결정일", "d1_prodlm_ostk": "1일 매수한도(보통)", "d1_prodlm_estk": "1일 매수한도(기타)",
    "dppln_stk_ostk": "처분예정주식(보통)", "dppln_stk_estk": "처분예정주식(기타)", "dpstk_prc_ostk": "처분대상 주식가격(보통)",
    "dpstk_prc_estk": "처분대상 주식가격(기타)", "dppln_prc_ostk": "처분예정금액(보통,원)", "dppln_prc_estk": "처분예정금액(기타,원)",
    "dpprpd_bgd": "처분기간(시작)", "dpprpd_edd": "처분기간(종료)", "dp_pp": "처분목적", "dp_m_mkt": "장내매도(주)",
    "dp_m_ovtm": "시간외대량매매(주)", "dp_m_otc": "장외처분(주)", "dp_m_etc": "기타처분(주)", "dp_dd": "처분결정일",
    "d1_slodlm_ostk": "1일 매도한도(보통)", "d1_slodlm_estk": "1일 매도한도(기타)",
    "ctr_prc": "계약금액(원)", "ctr_pd_bgd": "계약기간(시작)", "ctr_pd_edd": "계약기간(종료)", "ctr_pp": "계약목적",
    "ctr_cns_int": "계약체결기관", "ctr_cns_prd": "계약체결 예정일", "ctr_prc_bfcc": "해지전 계약금액", "ctr_prc_atcc": "해지후 계약금액",
    "ctr_pd_bfcc_bgd": "해지전 계약기간(시작)", "ctr_pd_bfcc_edd": "해지전 계약기간(종료)", "cc_pp": "해지목적", "cc_int": "해지기관",
    "cc_prd": "해지예정일", "tp_rm_atcc": "해지후 신탁재산 반환방법",
}
_BOND = {
    "cv_rt": "전환비율(%)", "cv_prc": "전환가액(원)", "cvisstk_knd": "전환주식 종류", "cvisstk_cnt": "전환주식수",
    "cvisstk_tisstk_vs": "주식총수 대비(%)", "cvrqpd_bgd": "전환청구(시작)", "cvrqpd_edd": "전환청구(종료)",
    "act_mktprcfl_cvprc_lwtrsprc": "리픽싱 최저조정가액(원)", "act_mktprcfl_cvprc_lwtrsprc_bs": "최저조정가액 근거",
    "rmislmt_lt70p": "70% 미만 조정가능 잔여한도(원)",
    "ex_rt": "행사(교환)비율(%)", "ex_prc": "행사(교환)가액(원)", "ex_prc_dmth": "행사(교환)가액 결정방법",
    "bdwt_div_atn": "사채·인수권 분리여부", "nstk_pym_mth": "신주대금 납입방법", "nstk_isstk_knd": "발행할 주식 종류",
    "nstk_isstk_cnt": "발행할 주식수", "nstk_isstk_tisstk_vs": "주식총수 대비(%)", "expd_bgd": "권리행사(시작)",
    "expd_edd": "권리행사(종료)", "extg": "교환대상(종류)", "extg_stkcnt": "교환대상 주식수", "extg_tisstk_vs": "주식총수 대비(%)",
    "exrqpd_bgd": "교환청구(시작)", "exrqpd_edd": "교환청구(종료)", "dbtrs_sc": "채무재조정 범위",
}
_OV = {
    "lstprstk_ostk_cnt": "상장예정주식(보통)", "lstprstk_estk_cnt": "상장예정주식(기타)", "tisstk_ostk": "발행주식총수(보통)",
    "tisstk_estk": "발행주식총수(기타)", "psmth_nstk_sl": "공모-신주발행(주)", "psmth_ostk_sl": "공모-구주매출(주)",
    "fdpp": "자금조달 목적", "lststk_orlst": "원주상장(주)", "lststk_drlst": "DR상장(주)", "lstex_nt": "상장거래소(국가)",
    "lstpp": "해외상장목적", "lstprd": "상장예정일", "dlststk_ostk_cnt": "상장폐지주식(보통)", "dlststk_estk_cnt": "상장폐지주식(기타)",
    "dlstrq_prd": "폐지신청예정일", "dlst_prd": "폐지(예정)일", "dlst_rs": "폐지사유", "lststk_ostk_cnt": "상장주식(보통)",
    "lststk_estk_cnt": "상장주식(기타)", "stk_cd": "종목코드", "lstd": "상장일", "tredd": "매매거래종료일",
}

_ev = [
    ("astInhtrfEtcPtbkOpt", "자산양수도(기타), 풋백옵션", ["풋백옵션", "자산양수도"],
     {"rp_rsn": "보고사유", "ast_inhtrf_prc": "자산양수도 가액"}),
    ("dfOcr", "부도발생", ["부도"], {"df_cn": "부도내용", "df_amt": "부도금액", "df_bnk": "부도발생은행",
                                    "dfd": "최종부도일", "df_rs": "부도사유 및 경위"}),
    ("bsnSp", "영업정지", [], {"bsnsp_rm": "영업정지 분야", "bsnsp_amt": "영업정지금액", "rsl": "최근매출총액",
                              "sl_vs": "매출액 대비", "ls_atn": "대규모법인 여부", "krx_stt_atn": "거래소 의무공시 해당",
                              "bsnsp_cn": "영업정지 내용", "bsnsp_rs": "영업정지 사유", "ft_ctp": "향후대책",
                              "bsnsp_af": "영업정지 영향", "bsnspd": "영업정지일자"}),
    ("ctrcvsBgrq", "회생절차 개시신청", ["회생", "법정관리"], {"apcnt": "신청인", "cpct": "관할법원", "rq_rs": "신청사유",
                                                       "rqd": "신청일자", "ft_ctp_sc": "향후대책 및 일정"}),
    ("dsRsOcr", "해산사유 발생", ["해산"], {"ds_rs": "해산사유", "ds_rsd": "해산사유 발생일"}),
    ("piicDecsn", "유상증자 결정", ["유상증자"], _NSTK),
    ("fricDecsn", "무상증자 결정", ["무상증자"], _NSTK),
    ("pifricDecsn", "유무상증자 결정", ["유무상증자"], _PIFRIC),
    ("crDecsn", "감자 결정", ["감자"], {
        "crstk_ostk_cnt": "감자주식(보통)", "crstk_estk_cnt": "감자주식(기타)", "fv_ps": "1주당 액면가",
        "bfcr_cpt": "감자전 자본금", "atcr_cpt": "감자후 자본금", "bfcr_tisstk_ostk": "감자전 주식수(보통)",
        "atcr_tisstk_ostk": "감자후 주식수(보통)", "bfcr_tisstk_estk": "감자전 주식수(기타)", "atcr_tisstk_estk": "감자후 주식수(기타)",
        "cr_rt_ostk": "감자비율(보통,%)", "cr_rt_estk": "감자비율(기타,%)", "cr_std": "감자기준일", "cr_mth": "감자방법",
        "cr_rs": "감자사유", "crsc_gmtsck_prd": "주주총회 예정일", "crsc_trnmsppd": "명의개서정지기간",
        "crsc_osprpd": "구주권 제출기간", "crsc_trspprpd": "매매거래 정지예정기간", "crsc_osprpd_bgd": "구주권제출(시작)",
        "crsc_osprpd_edd": "구주권제출(종료)", "crsc_trspprpd_bgd": "매매정지(시작)", "crsc_trspprpd_edd": "매매정지(종료)",
        "crsc_nstkdlprd": "신주권교부예정일", "crsc_nstklstprd": "신주상장예정일", "cdobprpd_bgd": "채권자이의(시작)",
        "cdobprpd_edd": "채권자이의(종료)", "ospr_nstkdl_pl": "구주권제출·신주교부 장소"}),
    ("bnkMngtPcbg", "채권은행 등의 관리절차 개시", ["워크아웃", "관리절차개시"], {
        "mngt_pcbg_dd": "관리절차개시 결정일", "mngt_int": "관리기관", "mngt_pd": "관리기간", "mngt_rs": "관리사유"}),
    ("lwstLg", "소송 등의 제기", ["소송"], {"icnm": "사건명", "ac_ap": "원고·신청인", "rq_cn": "청구내용",
                                        "cpct": "관할법원", "ft_ctp": "향후대책", "lgd": "제기일자"}),
    ("ovLstDecsn", "해외 증권시장 주권등 상장 결정", ["해외상장결정"], _OV),
    ("ovDlstDecsn", "해외 증권시장 주권등 상장폐지 결정", ["해외상장폐지결정"], _OV),
    ("ovLst", "해외 증권시장 주권등 상장", ["해외상장"], _OV),
    ("ovDlst", "해외 증권시장 주권등 상장폐지", ["해외상장폐지"], _OV),
    ("cvbdIsDecsn", "전환사채권 발행결정", ["전환사채", "CB"], _BOND),
    ("bdwtIsDecsn", "신주인수권부사채권 발행결정", ["신주인수권부사채", "BW"], _BOND),
    ("exbdIsDecsn", "교환사채권 발행결정", ["교환사채", "EB"], _BOND),
    ("bnkMngtPcsp", "채권은행 등의 관리절차 중단", ["관리절차중단"], {
        "mngt_pcsp_dd": "관리절차중단 결정일", "mngt_int": "관리기관", "sp_rs": "중단사유", "ft_ctp": "향후대책"}),
    ("wdCocobdIsDecsn", "상각형 조건부자본증권 발행결정", ["조건부자본증권발행", "코코본드발행"], _BOND),
    ("tsstkAqDecsn", "자기주식 취득 결정", ["자사주취득", "자기주식취득"], _TSSTK),
    ("tsstkDpDecsn", "자기주식 처분 결정", ["자사주처분", "자기주식처분"], _TSSTK),
    ("tsstkAqTrctrCnsDecsn", "자기주식취득 신탁계약 체결 결정", ["자사주신탁체결"], _TSSTK),
    ("tsstkAqTrctrCcDecsn", "자기주식취득 신탁계약 해지 결정", ["자사주신탁해지"], _TSSTK),
    ("bsnInhDecsn", "영업양수 결정", ["영업양수"], _BSN),
    ("bsnTrfDecsn", "영업양도 결정", ["영업양도"], _BSN),
    ("tgastInhDecsn", "유형자산 양수 결정", ["유형자산양수"], _ASSET_TRADE),
    ("tgastTrfDecsn", "유형자산 양도 결정", ["유형자산양도"], _ASSET_TRADE),
    ("otcprStkInvscrInhDecsn", "타법인 주식 및 출자증권 양수결정", ["타법인주식양수", "지분인수", "M&A"], _OTC),
    ("otcprStkInvscrTrfDecsn", "타법인 주식 및 출자증권 양도결정", ["타법인주식양도", "지분매각"], _OTC),
    ("stkrtbdInhDecsn", "주권 관련 사채권 양수 결정", ["사채권양수"], _STKRTBD),
    ("stkrtbdTrfDecsn", "주권 관련 사채권 양도 결정", ["사채권양도"], _STKRTBD),
    ("cmpMgDecsn", "회사합병 결정", ["합병"], _MG),
    ("cmpDvDecsn", "회사분할 결정", ["분할", "물적분할", "인적분할"], _DV),
    ("cmpDvmgDecsn", "회사분할합병 결정", ["분할합병"], _DVMG),
    ("stkExtrDecsn", "주식교환·이전 결정", ["주식교환", "주식이전", "포괄적교환"], {
        "extr_sen": "구분", "extr_stn": "교환·이전 형태", "extr_tgcmp_cmpnm": "대상법인", "extr_tgcmp_rp": "대상법인 대표자",
        "extr_tgcmp_mbsn": "대상법인 주요사업", "extr_tgcmp_rl_cmpn": "대상법인과의 관계",
        "extr_tgcmp_tisstk_ostk": "대상법인 발행주식(보통)", "extr_tgcmp_tisstk_cstk": "대상법인 발행주식(종류)",
        "rbsnfdtl_tast": "대상법인 자산총계", "rbsnfdtl_tdbt": "대상법인 부채총계", "rbsnfdtl_teqt": "대상법인 자본총계",
        "rbsnfdtl_cpt": "대상법인 자본금", "extr_rt": "교환·이전 비율", "extr_rt_bs": "비율 산출근거", "extr_pp": "교환·이전 목적",
        "extrsc_extrctrd": "계약일", "extrsc_shddstd": "주주확정기준일", "extrsc_gmtsck_prd": "주주총회 예정일",
        "extrsc_aprskh_expd_bgd": "매수청구(시작)", "extrsc_aprskh_expd_edd": "매수청구(종료)", "extrsc_extrdt": "교환·이전일",
        "extrsc_nstklstprd": "신주 상장예정일", "atextr_cpcmpnm": "완전모회사명"}),
]
for _key, _name, _aliases, _labels in _ev:
    _add(_key, "DS005", _name, "event", _aliases, _labels)

# ---------------- DS006 증권신고서 ----------------
for _key, _name, _aliases in [
    ("estkRs", "지분증권", ["유상증자신고서", "IPO", "공모"]),
    ("bdRs", "채무증권", ["회사채신고서"]),
    ("stkdpRs", "증권예탁증권", ["DR"]),
    ("mgRs", "합병", ["합병신고서"]),
    ("extrRs", "주식의포괄적교환·이전", ["교환이전신고서"]),
    ("dvRs", "분할", ["분할신고서"]),
]:
    _add(_key, "DS006", "증권신고서(" + _name + ")", "event", _aliases, {
        "tm": "회차", "bdnmn": "채무증권 명칭", "slmth": "모집(매출)방법", "fta": "권면총액", "isprc": "발행가액",
        "intr": "이자율", "isrr": "발행수익률", "rpd": "상환기일", "print_pymint": "원리금지급대행기관",
        "mngt_cmp": "사채관리회사", "cdrt_int": "신용등급(평가기관)", "dpcrn": "표시통화", "dpcr_amt": "표시통화 발행규모",
        "usarn": "사용지역", "usntn": "사용국가", "wnexpl_at": "원화교환 예정여부", "udtintnm": "인수기관명",
        "grt_int": "보증기관", "grt_amt": "보증금액", "icmg_mgknd": "담보 종류", "icmg_mgamt": "담보금액",
        "estk_exstk": "연계 행사대상증권", "estk_exrt": "연계 권리행사비율", "estk_exprc": "연계 권리행사가격",
        "estk_expd": "연계 권리행사기간", "drcb_at": "파생결합사채 여부", "drcb_uast": "기초자산",
        "drcb_optknd": "옵션종류", "drcb_mtd": "만기일"})

ENDPOINTS = {e["key"]: e for e in _E}


def labels_for(key: str) -> dict:
    e = ENDPOINTS.get(key)
    d = dict(COMMON_LABELS)
    if e:
        d.update(e["labels"])
    return d


def norm(s: str) -> str:
    """비교용 정규화: 한글·영문·숫자만 남기고 소문자."""
    import re
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", s or "").lower()


def find_endpoints(query: str, kinds=None, groups=None) -> list[dict]:
    """한글명/별칭/엔드포인트명으로 검색. 정확히 맞는 것 우선."""
    q = norm(query)
    cands = [e for e in _E if (not kinds or e["kind"] in kinds) and (not groups or e["group"] in groups)]
    exact, partial = [], []
    for e in cands:
        names = [e["key"], e["name"]] + e["aliases"]
        ns = [norm(n) for n in names]
        if q in ns:
            exact.append(e)
        elif any(q in n for n in ns) or any(n and n in q for n in ns[1:2]):
            partial.append(e)
    return exact or partial
