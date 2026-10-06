"""
Offertanfrage als PDF und als E-Mail-Entwurf (FA-1612, FA-1614 a/c).
"""
from __future__ import annotations
import email
import os
import sys
from email import policy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.models.project import KnxProject
from knix_arranger.models.quotation import QuotationItem, QuotationRequest, Supplier
from knix_arranger.services.quotation_request_service import (
    display_date, offer_deadline, request_filename, write_request_email,
    write_request_pdf,
)


def _data():
    project = KnxProject(name="Chalet Muster", project_number="P-23")
    project.client_profile.object_address = "Dorfstrasse 1, 3988 Obergesteln"
    supplier = Supplier(company_name="Elektro Grosshandel AG", contact_person="Frau Meier",
                        email="offerte@grosshandel.ch", address="Industriestrasse 5")
    qr = QuotationRequest(request_number="OA-2026-001", date_created="2026-10-06",
                          delivery_date_requested="2026-11-30", items=[
                              QuotationItem(position=1, manufacturer="MDT",
                                            order_number="AKS-0816.03",
                                            product_name="Schaltaktor 8-fach", quantity=2),
                              QuotationItem(position=2, manufacturer="MDT",
                                            order_number="BE-TA55P6.01",
                                            product_name="Taster 6-fach", quantity=7,
                                            notes="weiss")])
    company = CompanyProfile(company_name="Müller SmartHome", user_name="M. Müller",
                             email="info@mueller.ch", phone="079 000 00 00")
    return project, supplier, qr, company


def test_dates():
    _, _, qr, _ = _data()
    assert offer_deadline(qr) == "20.10.2026"
    assert display_date("2026-11-30") == "30.11.2026"
    assert display_date("30.11.2026") == "30.11.2026"
    assert display_date("Ende Monat") == "Ende Monat"


def test_filename():
    _, supplier, qr, _ = _data()
    assert request_filename(qr, supplier, "pdf") == \
        "Offertanfrage_OA-2026-001_Elektro_Grosshandel_AG.pdf"


def test_pdf_contains_fa1612_parts(tmp_path):
    project, supplier, qr, company = _data()
    path = tmp_path / "anfrage.pdf"
    write_request_pdf(project, qr, supplier, company, str(path))
    with fitz.open(path) as doc:
        text = " ".join("".join(page.get_text() for page in doc).split())
    for part in ("Offertanfrage OA-2026-001", "Elektro Grosshandel AG", "z.H. Frau Meier",
                 "P-23", "Dorfstrasse 1", "30.11.2026", "AKS-0816.03",
                 "Schaltaktor 8-fach", "weiss", "Offerte erbeten bis: 20.10.2026",
                 "Unterschrift"):
        assert part in text, part


def test_email_draft_with_pdf_attachment(tmp_path):
    project, supplier, qr, company = _data()
    eml = write_request_email(project, qr, supplier, company, str(tmp_path))
    assert os.path.basename(eml) == "Offertanfrage_OA-2026-001_Elektro_Grosshandel_AG.eml"
    with open(eml, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=policy.default)
    assert msg["X-Unsent"] == "1"
    assert msg["To"] == "offerte@grosshandel.ch"
    assert msg["From"] == "info@mueller.ch"
    assert msg["Subject"] == "Offertanfrage OA-2026-001 – Chalet Muster"
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert body.startswith("Guten Tag Frau Meier")
    assert "2 Positionen" in body and "bis 20.10.2026" in body
    attachments = list(msg.iter_attachments())
    assert [a.get_filename() for a in attachments] == [
        "Offertanfrage_OA-2026-001_Elektro_Grosshandel_AG.pdf"]
    assert attachments[0].get_content().startswith(b"%PDF")


def test_email_without_supplier_address(tmp_path):
    project, supplier, qr, company = _data()
    supplier.email = ""
    supplier.contact_person = ""
    eml = write_request_email(project, qr, supplier, company, str(tmp_path))
    with open(eml, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=policy.default)
    assert msg["To"] is None
    assert msg.get_body(preferencelist=("plain",)).get_content().startswith(
        "Sehr geehrte Damen und Herren")


def test_view_email_marks_request_as_sent(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication, QMessageBox
    from knix_arranger.ui.views import quotation_view
    from knix_arranger.ui.views.quotation_view import QuotationView
    QApplication.instance() or QApplication([])

    project, supplier, qr, company = _data()
    project._file_path = str(tmp_path / "Chalet.knxarr")
    project.suppliers = [supplier]
    qr.supplier_id = supplier.id
    project.quotation_requests = [qr]
    view = QuotationView()
    view.set_project(project)
    view._request_table.setCurrentCell(0, 0)

    with patch.object(QuotationView, "_company_profile", return_value=company), \
         patch.object(quotation_view.os, "startfile", create=True) as opened, \
         patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        view._email_request()

    eml = opened.call_args[0][0]
    assert eml.endswith(".eml")
    assert os.path.dirname(eml) == str(tmp_path / "Berichte" / "Offertanfragen")
    assert qr.status == "Versendet" and qr.date_sent
