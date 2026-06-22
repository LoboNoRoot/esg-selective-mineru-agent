from pathlib import Path

from esg_selective_mineru.report_filter import assess_report_suitability


def test_legacy_social_responsibility_report_is_skipped():
    pdf = Path(
        r"C:\Users\18130\PycharmProjects\爬虫\提取\esg报告提取\esg报告爬取\cninfo_esg_data\pdfs"
        r"\000690_宝新能源_2024_宝新能源：2024年度社会责任报告.pdf"
    )
    if not pdf.exists():
        return
    result = assess_report_suitability(pdf)
    assert result["should_skip"] is True
    assert result["reason_code"] == "legacy_social_responsibility_report"
