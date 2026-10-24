"""CardCrop dialogs: eBay account and review, folders, Instagram, identify, calibrate, arrange."""
from __future__ import annotations

import cv2
import ebay
import engine
import identify
import json
import listing
import numpy as np
import os
import re
import time
from PySide6.QtCore import QRectF, QSettings, QThreadPool, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget
import ui_base as TH

class EbayAccountDialog(QDialog):
    """Keys, one-time sign-in, ship-from ZIP and the three business policies."""

    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("eBay account")
        self.resize(760, 640)
        self.setStyleSheet(TH.STYLE)
        v = QVBoxLayout(self)
        edit = ""

        def field(label, text="", secret=False, ph=""):
            v.addWidget(QLabel(label, objectName="muted"))
            e = QLineEdit(text)
            e.setStyleSheet(edit)
            e.setPlaceholderText(ph)
            if secret:
                e.setEchoMode(QLineEdit.Password)
            v.addWidget(e)
            return e
        v.addWidget(QLabel("1  Keys", objectName="h"))
        self.app_id = field("App ID (Client ID), from the Production keyset", str(cfg.value("ebay_app_id", "")))
        self.runame = field("RuName (eBay Redirect URL name)", str(cfg.value("ebay_runame", "")))
        has_cert = bool(self.app_id.text() and ebay.secret_get(f"cert:{self.app_id.text().strip()}"))
        self.cert = field("Cert ID (Client Secret): kept in your Mac's Keychain", "", True,
                          "Saved in Keychain; type a new one to replace it" if has_cert else "PRD-…")
        v.addWidget(QLabel("2  Sign in", objectName="h"))
        r = QHBoxLayout()
        b_open = QPushButton("Open eBay sign-in")
        b_open.clicked.connect(self.open_signin)
        r.addWidget(b_open)
        self.state = QLabel("", objectName="muted")
        r.addWidget(self.state, 1)
        v.addLayout(r)
        self.pasted = field("After you agree, eBay shows “Authorization successfully completed”. "
                            "Copy that page's whole address from the address bar and paste it here:")
        b_finish = QPushButton("Finish sign-in")
        b_finish.clicked.connect(self.finish)
        v.addWidget(b_finish, 0, Qt.AlignLeft)
        v.addWidget(QLabel("3  Shipping and policies", objectName="h"))
        self.zip = field("Ship-from ZIP code", str(cfg.value("ebay_zip", "")))
        self.pol = {}
        g = QGridLayout()
        for i, (kind, label) in enumerate((("fulfillment", "Shipping policy"), ("return", "Return policy"),
                                           ("payment", "Payment policy"))):
            g.addWidget(QLabel(label), i, 0)
            c = QComboBox()
            saved = cfg.value(f"ebay_pol_{kind}", "")
            if saved:
                c.addItem(str(cfg.value(f"ebay_pol_{kind}_name", saved)), saved)
            g.addWidget(c, i, 1)
            self.pol[kind] = c
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        b_ref = QPushButton("Load my policies from eBay")
        b_ref.clicked.connect(self.load_policies)
        v.addWidget(b_ref, 0, Qt.AlignLeft)
        v.addWidget(QLabel("Package (calculated shipping needs it): weight in ounces, then length × width × "
                           "height in inches", objectName="muted"))
        pk = QHBoxLayout()
        self.pkg = {}
        for key, label, default, hi in (("oz", "oz", 3.0, 160), ("l", "L", 6.0, 60), ("w", "W", 4.0, 60),
                                        ("h", "H", 1.0, 60)):
            sp = QDoubleSpinBox()
            sp.setRange(0.1, hi)
            sp.setDecimals(1)
            sp.setValue(float(cfg.value(f"ebay_pkg_{key}", default)))
            pk.addWidget(QLabel(label))
            pk.addWidget(sp, 1)
            self.pkg[key] = sp
        v.addLayout(pk)
        v.addWidget(QLabel("4  Seller Hub drafts", objectName="h"))
        tr = QHBoxLayout()
        self.tpl = QLabel(str(cfg.value("ebay_template", "")) or "No drafts template chosen yet")
        self.tpl.setWordWrap(True)
        tr.addWidget(self.tpl, 1)
        b_tpl = QPushButton("Choose template…")
        b_tpl.setToolTip("Seller Hub > Reports > Uploads > Get template > Create new drafts")
        b_tpl.clicked.connect(self.choose_template)
        tr.addWidget(b_tpl)
        v.addLayout(tr)
        v.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._show_state()

    def client(self):
        c = ebay.Client(self.app_id.text(), self.runame.text())
        if self.cert.text().strip():
            c.save_cert(self.cert.text())
            self.cert.clear()
            self.cert.setPlaceholderText("Saved in Keychain; type a new one to replace it")
        return c

    def _show_state(self):
        c = ebay.Client(self.app_id.text(), self.runame.text())
        if c.app_id and c.signed_in():
            self.state.setText(f"<span style='color:{TH.OK}'>Signed in</span>")
        else:
            self.state.setText("Not signed in yet")

    def _need(self):
        if not self.app_id.text().strip() or not self.runame.text().strip():
            QMessageBox.information(self, "Keys needed", "Enter the App ID and the RuName first.")
            return False
        if not self.cert.text().strip() and not ebay.secret_get(f"cert:{self.app_id.text().strip()}"):
            QMessageBox.information(self, "Keys needed", "Enter the Cert ID first.")
            return False
        return True

    def open_signin(self):
        if not self._need():
            return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(self.client().auth_url()))
        self.state.setText("Sign in and agree in your browser, then paste the address below")

    def finish(self):
        if not self._need() or not self.pasted.text().strip():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.client().exchange(self.pasted.text())
            self.pasted.clear()
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Sign-in failed", f"{e}\n\nThe code from eBay only lasts a few minutes: "
                                "open the sign-in again and paste the new address straight away.")
            return
        QApplication.restoreOverrideCursor()
        self._show_state()
        self.load_policies()

    def load_policies(self):
        if not self._need():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pols = self.client().policies()
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Could not load policies", str(e))
            return
        QApplication.restoreOverrideCursor()
        for kind, combo in self.pol.items():
            keep = combo.currentData()
            combo.clear()
            for pid, name in pols.get(kind, []):
                combo.addItem(name, pid)
            i = combo.findData(keep)
            combo.setCurrentIndex(max(0, i))
        if not any(pols.values()):
            QMessageBox.information(self, "No policies", "Your account has no business policies yet. Create a "
                                    "shipping, return and payment policy in Seller Hub, then load them again.")

    def choose_template(self):
        p, _ = QFileDialog.getOpenFileName(self, "eBay Create drafts template",
                                           os.path.expanduser("~/Downloads"), "CSV files (*.csv)")
        if p:
            self.cfg.setValue("ebay_template", p)
            self.tpl.setText(p)

    def save(self):
        for key, sp in self.pkg.items():
            self.cfg.setValue(f"ebay_pkg_{key}", sp.value())
        if self.cert.text().strip() and self.app_id.text().strip():
            self.client()
        self.cfg.setValue("ebay_app_id", self.app_id.text().strip())
        self.cfg.setValue("ebay_runame", self.runame.text().strip())
        z = self.zip.text().strip()
        if z != str(self.cfg.value("ebay_zip", "")):
            self.cfg.setValue("ebay_location_zip", "")      # set the location again on the next upload
        self.cfg.setValue("ebay_zip", z)
        for kind, combo in self.pol.items():
            if combo.currentData():
                self.cfg.setValue(f"ebay_pol_{kind}", combo.currentData())
                self.cfg.setValue(f"ebay_pol_{kind}_name", combo.currentText())
        self.accept()


class EbayReviewDialog(QDialog):
    """Everything uploaded but not yet live: check it, then publish or remove it."""

    def __init__(self, parent, client, out_dir):
        super().__init__(parent)
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
        self.QTableWidgetItem = QTableWidgetItem
        self.c, self.out_dir = client, out_dir
        self.setWindowTitle("Review eBay listings")
        self.resize(1100, 640)
        self.setStyleSheet(TH.STYLE)
        v = QVBoxLayout(self)
        tip = QLabel("Nothing here is live until you publish it. Tick the ones you have checked, then press "
                     "Publish selected. To change a listing, fix it in CardCrop and upload it again: the "
                     "unpublished listing is updated in place.", objectName="muted")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.t = QTableWidget(0, 6)
        self.t.setHorizontalHeaderLabels(["", "Title", "Price", "Condition", "Photos", "Status"])
        self.t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.t.verticalHeader().setVisible(False)
        self.t.setSelectionMode(QAbstractItemView.NoSelection)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.cellDoubleClicked.connect(self._open)
        v.addWidget(self.t, 1)
        r = QHBoxLayout()
        self.b_pub = QPushButton("Publish selected", objectName="primary")
        self.b_pub.clicked.connect(self.publish)
        b_del = QPushButton("Remove selected from eBay")
        b_del.clicked.connect(self.remove)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.accept)
        for b in tick_buttons(self.t):
            r.addWidget(b)
        r.addSpacing(12)
        r.addWidget(self.b_pub); r.addWidget(b_del); r.addStretch(1); r.addWidget(b_close)
        v.addLayout(r)
        self.reload()

    def reload(self):
        # drafts live in Seller Hub, not behind the API, so only uploaded offers are listed here
        self.recs = {k: v for k, v in ebay.load_records(self.out_dir).items() if v.get("offer_id")}
        rows = sorted(self.recs.items(), key=lambda kv: (kv[1].get("status") != "unpublished",
                                                         kv[1].get("uploaded", "")), reverse=False)
        self.skus = [k for k, _ in rows]
        self.t.setRowCount(len(rows))
        for i, (sku, r) in enumerate(rows):
            chk = self.QTableWidgetItem()
            live = r.get("status") == "published"
            chk.setFlags(Qt.ItemIsEnabled | (Qt.NoItemFlags if live else Qt.ItemIsUserCheckable))
            if not live:
                chk.setCheckState(Qt.Unchecked)
            self.t.setItem(i, 0, chk)
            status = (f"Live · {r.get('listing_id')}  (double-click to open)" if live
                      else f"Unpublished · uploaded {r.get('uploaded', '')}")
            for col, text in ((1, r.get("title", sku)), (2, f"${float(r.get('price', 0)):.2f}"),
                              (3, r.get("condition", "")), (4, str(r.get("photos", ""))), (5, status)):
                it = self.QTableWidgetItem(text)
                if live:
                    it.setForeground(QColor(TH.OK))
                self.t.setItem(i, col, it)
        self.t.resizeColumnsToContents()
        self.t.horizontalHeader().setStretchLastSection(True)

    def _checked(self):
        return [self.skus[i] for i in range(self.t.rowCount())
                if self.t.item(i, 0).checkState() == Qt.Checked]

    def _open(self, row, _col):
        r = self.recs.get(self.skus[row], {})
        if r.get("listing_id"):
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(f"https://www.ebay.com/itm/{r['listing_id']}"))

    def _each(self, skus, verb, fn):
        failed = []
        for n, sku in enumerate(skus, 1):
            self.setWindowTitle(f"{verb} {n} of {len(skus)}…")
            QApplication.processEvents()
            try:
                fn(sku, self.recs[sku])
            except Exception as e:  # noqa: BLE001
                failed.append(f"{self.recs[sku].get('title', sku)}: {e}")
        self.setWindowTitle("Review eBay listings")
        self.reload()
        if failed:
            QMessageBox.warning(self, f"Some could not be {verb.lower()}ed".replace("eded", "ed"),
                                "\n\n".join(failed))

    def publish(self):
        skus = self._checked()
        if not skus:
            return
        if QMessageBox.question(self, "Publish", f"Put {len(skus)} listing(s) live on eBay now?") != QMessageBox.Yes:
            return

        def go(sku, r):
            lid = self.c.publish(r["offer_id"])
            ebay.save_record(self.out_dir, sku, {"status": "published", "listing_id": lid,
                                                 "published": time.strftime("%Y-%m-%d %H:%M")})
        self._each(skus, "Publish", go)

    def remove(self):
        skus = self._checked()
        if not skus or QMessageBox.question(
                self, "Remove", f"Remove {len(skus)} unpublished listing(s) from eBay? "
                                "Your photos and files in CardCrop stay.") != QMessageBox.Yes:
            return

        def go(sku, r):
            self.c.delete_offer(r["offer_id"])
            allr = ebay.load_records(self.out_dir)
            allr.pop(sku, None)
            with open(ebay.record_path(self.out_dir), "w", encoding="utf-8") as f:
                json.dump(allr, f, ensure_ascii=False, indent=2)
        self._each(skus, "Remove", go)


class FolderListDialog(QDialog):
    """List cards on eBay straight from folders you exported earlier: no shooting,
    no exporting. One folder is one card; its photos go up in file-name order."""

    def __init__(self, main, folders):
        super().__init__(main)
        from PySide6.QtWidgets import QTableWidget, QHeaderView, QAbstractItemView
        self.m = main
        self.setWindowTitle("List exported folders on eBay")
        self.resize(1180, 680)
        self.setStyleSheet(TH.STYLE)
        v = QVBoxLayout(self)
        tip = QLabel("Each folder is one card. CardCrop reads the card from the folder or file names "
                     "(like lugia-v-swsh12-185) or from a saved listing, and the condition from names like "
                     "_back_LP. Fill in anything missing, tick the rows and upload: nothing goes live until "
                     "you publish it in Review and publish.", objectName="muted")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.t = QTableWidget(0, 8)
        self.t.setHorizontalHeaderLabels(["", "Folder", "Card", "Condition", "Price $", "Photos", "Status",
                                          "Market now"])
        self.t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.t.verticalHeader().setVisible(False)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.cellDoubleClicked.connect(self._double)
        v.addWidget(self.t, 1)
        r = QHBoxLayout()
        b_add = QPushButton("Add folders…")
        b_add.clicked.connect(self.add_dialog)
        b_id = QPushButton("Identify selected…")
        b_id.clicked.connect(lambda: self.identify_row(self.t.currentRow()))
        drafts_first = self.m.ebay_route() == "drafts"
        self.b_drafts = QPushButton("Make Seller Hub drafts", objectName="primary" if drafts_first else "")
        self.b_drafts.setToolTip("Uploads the photos, then writes a drafts file for Seller Hub; every card "
                                 "lands in your eBay Drafts, with photos, for you to finish and list")
        self.b_drafts.clicked.connect(self.make_drafts)
        self.b_up = QPushButton("Upload unpublished (API)", objectName="" if drafts_first else "primary")
        self.b_up.setToolTip("Creates unpublished listings that you publish from Review and publish")
        self.b_up.clicked.connect(self.upload)
        b_rev = QPushButton("Review and publish…")
        b_rev.clicked.connect(self.m.ebay_review)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.accept)
        for b in tick_buttons(self.t):
            r.addWidget(b)
        b_rep = QPushButton("Condition reports")
        b_rep.setToolTip("A condition report for each ticked folder, added as its last photo before uploading")
        b_rep.clicked.connect(self.make_reports)
        for b in (b_add, b_id, b_rep):
            r.addWidget(b)
        r.addStretch(1)
        for b in ((self.b_up, self.b_drafts) if not drafts_first else (self.b_drafts, self.b_up)) + (b_rev, b_close):
            r.addWidget(b)
        v.addLayout(r)
        self.rows = []          # dicts: folder, info, cond, cent, photos
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.add(folders)

    # ---------------------------------------------------------- rows
    def add_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "A card folder, or a folder of card folders",
                                             self.m.out_dir)
        if d:
            self.add([d])

    @staticmethod
    def expand(folders):
        out = []
        for f in folders:
            f = os.path.normpath(f)              # "card/" would otherwise have no name
            if not os.path.isdir(f):
                continue
            if looks_exported(f) or ebay.listing_photos(f):
                if looks_exported(f) or not any(os.path.isdir(os.path.join(f, x)) for x in os.listdir(f)):
                    out.append(f)
                    continue
            for sub in sorted(os.listdir(f)):           # a parent folder: every card folder inside
                p = os.path.join(f, sub)
                if os.path.isdir(p) and sub != "instagram" and ebay.listing_photos(p):
                    out.append(p)
        return out

    def add(self, folders):
        from PySide6.QtWidgets import QTableWidgetItem
        known = {r["folder"] for r in self.rows}
        prices = self.m._prices()
        for f in self.expand(folders):
            if f in known:
                continue
            info, cond, cent = folder_listing_info(f)
            row = {"folder": f, "info": info, "cond": cond, "cent": cent, "photos": ebay.listing_photos(f)}
            self.rows.append(row)
            i = self.t.rowCount()
            self.t.insertRow(i)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            chk.setCheckState(Qt.Checked)
            self.t.setItem(i, 0, chk)
            self.t.setItem(i, 1, QTableWidgetItem(os.path.basename(f)))
            self.t.setItem(i, 2, QTableWidgetItem(""))
            cc = QComboBox()
            cc.addItem("Choose…", "")
            for code in listing.CONDITIONS:
                cc.addItem(code, code)
            cc.setCurrentIndex(max(0, cc.findData(cond)))
            self.t.setCellWidget(i, 3, cc)
            ps = PriceBox()
            ps.setRange(0, 100000)
            ps.setDecimals(2)
            ps.setValue(float(prices.get(os.path.basename(f), 0)))
            self.t.setCellWidget(i, 4, ps)
            self.t.setItem(i, 5, QTableWidgetItem(str(len(row["photos"]))))
            self.t.setItem(i, 6, QTableWidgetItem(""))
            self.t.setItem(i, 7, QTableWidgetItem(""))
            self._show_card(i)
            if info is not None:
                self._price_row(i)
            if info is None:
                self.t.item(i, 2).setText("Looking up…")
                task = FolderIdTask(self.m.db, i, f)
                task.sig.done.connect(self._identified)
                self.pool.start(task)
        self.t.resizeColumnsToContents()
        from PySide6.QtWidgets import QHeaderView
        self.t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

    def make_reports(self):
        rows = [(i, row) for i, row in enumerate(self.rows) if self.t.item(i, 0).checkState() == Qt.Checked]
        if not rows:
            return
        self.m.batch_reports([os.path.basename(r["folder"]) for _, r in rows], [r["folder"] for _, r in rows],
                             [r["info"] for _, r in rows])
        for i, row in rows:                        # the report is one more photo to upload
            row["photos"] = ebay.listing_photos(row["folder"])
            self.t.item(i, 5).setText(str(len(row["photos"])))

    def _double(self, r, c):
        if c == 2:
            self.identify_row(r)
        elif c == 6 and self.rows[r].get("error"):
            box = QMessageBox(self)
            box.setWindowTitle("Upload failed")
            box.setText(self.rows[r]["error"])
            box.setInformativeText(f"The full exchange with eBay is in {ebay.log_path()}")
            box.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.exec()

    def _show_card(self, i):
        info = self.rows[i]["info"]
        it = self.t.item(i, 2)
        if info:
            it.setText(identify.CardInfo(**info).label())
            it.setForeground(QColor(TH.TEXT))
        else:
            it.setText("Not identified: double-click to search")
            it.setForeground(QColor(TH.WARN))

    def _identified(self, i, info):
        if 0 <= i < len(self.rows) and self.rows[i]["info"] is None:
            self.rows[i]["info"] = info
            self._show_card(i)
            if info:
                self._price_row(i)

    def _price_row(self, i):
        self.t.item(i, 7).setText("checking…")
        t = PriceTask(self.m.ebay_client(), self.m.db, self.rows[i]["info"], i)
        t.sig.done.connect(self._priced)
        self.pool.start(t)

    def _priced(self, i, r):
        if not 0 <= i < len(self.rows):
            return
        it = self.t.item(i, 7)
        sug = r.get("suggested")
        it.setText(f"${sug:.2f} suggested" if sug else "no data")
        it.setToolTip(re.sub(r"<[^>]+>", "", ebay.price_summary(r)).replace("  ·  ", "\n"))
        spin = self.t.cellWidget(i, 4)
        if sug and spin.value() == 0:          # fill only empty prices; yours always win
            spin.setValue(sug)

    def identify_row(self, i):
        if not 0 <= i < len(self.rows):
            return
        row = self.rows[i]
        q = (row["info"] or {}).get("name") or re.sub(r"[-_]+", " ", os.path.basename(row["folder"]))
        dlg = IdentifyDialog(self, self.m.db, q, str(self.m.cfg.value("id_lang", "en")))
        if dlg.exec() == QDialog.Accepted and dlg.choice is not None:
            row["info"] = dlg.choice.to_dict()
            self._show_card(i)
            self._price_row(i)

    # ---------------------------------------------------------- upload
    def _ready_rows(self):
        """(row, name, folder, L, price) for every ticked row that has what it needs."""
        todo, problems = [], []
        prices = self.m._prices()
        for i, row in enumerate(self.rows):
            if self.t.item(i, 0).checkState() != Qt.Checked:
                continue
            name = os.path.basename(row["folder"])
            cond = self.t.cellWidget(i, 3).currentData()
            price = self.t.cellWidget(i, 4).value()
            missing = [w for w, ok in (("the card", row["info"]), ("a condition", cond),
                                       ("a price", price > 0), ("photos", row["photos"])) if not ok]
            if missing:
                problems.append(f"{name}: needs {', '.join(missing)}")
                continue
            prices[name] = round(price, 2)
            L = listing.build(row["info"], ebay.sku_for(engine.safe_name(name)), row["cent"], "", cond, price,
                              has_corner_photos(row["folder"]))
            L["store_category"] = self.m.store_category_for(name)
            L["store_category2"] = self.m.store_category_for(name, 2)
            todo.append((i, name, row["folder"], L, price))
        self.m.cfg.setValue("prices", json.dumps(prices))
        if problems:
            QMessageBox.information(self, "Some rows are not ready", "\n".join(problems) +
                                    ("\n\nThe rest will go ahead." if todo else ""))
        return todo

    def make_drafts(self):
        c = self.m.ebay_client()
        if not c or not c.signed_in():
            QMessageBox.information(self, "Connect eBay first", "Open Account… in the Listing tab to sign in.")
            return
        tpl = str(self.m.cfg.value("ebay_template", ""))
        if not tpl or not os.path.exists(tpl):
            QMessageBox.information(
                self, "Drafts template needed",
                "CardCrop fills eBay's own drafts template. In Seller Hub open Reports > Uploads, click "
                "Get template and choose Create new drafts. Save the file it downloads, then pick it here.")
            tpl, _ = QFileDialog.getOpenFileName(self, "eBay Create drafts template",
                                                 os.path.expanduser("~/Downloads"), "CSV files (*.csv)")
            if not tpl:
                return
            self.m.cfg.setValue("ebay_template", tpl)
        todo = self._ready_rows()
        if not todo:
            return
        self.b_drafts.setEnabled(False)
        self.b_up.setEnabled(False)
        self._client, self._dq, self._drafts, self._tpl = c, list(todo), [], tpl
        self._draft_next()

    def _draft_next(self):
        if not self._dq:
            self._write_drafts()
            return
        i, name, folder, L, price = self._dq.pop(0)
        self._row, self._cur = i, (name, L, price)
        t = EbayPhotosTask(self._client, folder)
        t.sig.progress.connect(self._progress)
        t.sig.done.connect(self._draft_photos_done)
        if not hasattr(self.m, "net_pool"):
            self.m.net_pool = QThreadPool(self.m)
            self.m.net_pool.setMaxThreadCount(1)
        self.m.net_pool.start(t)

    def _draft_photos_done(self, urls, err):
        i = self._row
        self._end_progress(i)
        it = self.t.item(i, 6)
        if err:
            it.setText(f"Failed: {err}  (double-click for details)")
            it.setToolTip(err)
            it.setForeground(QColor(TH.WARN))
            self.rows[i]["error"] = err
        else:
            name, L, price = self._cur
            names = {k: str(self.m.cfg.value(f"ebay_pol_{k}_name", "")) for k in ("fulfillment", "return", "payment")}
            L = dict(L, extra=listing.draft_extras(urls, price, str(self.m.cfg.value("ebay_zip", "")),
                                                   names, self.m.ebay_package(), L.get("store_category"),
                                                   L.get("store_category2")))
            self._drafts.append(L)
            ebay.save_record(self.m.out_dir, ebay.sku_for(engine.safe_name(name)), {
                "name": name, "title": L["title"], "price": price, "condition": L.get("condition", ""),
                "photos": len(urls), "drafted": time.strftime("%Y-%m-%d %H:%M")})
            it.setText("Photos uploaded; in the drafts file")
            it.setForeground(QColor(TH.OK))
            self.t.item(i, 0).setCheckState(Qt.Unchecked)
        self._draft_next()

    def _write_drafts(self):
        self.b_drafts.setEnabled(True)
        self.b_up.setEnabled(True)
        if not self._drafts:
            return
        out = os.path.join(self.m.out_dir, f"ebay_drafts_{time.strftime('%Y%m%d-%H%M')}.csv")
        try:
            os.makedirs(self.m.out_dir, exist_ok=True)
            rep_ = listing.fill_ebay_template(self._tpl, self._drafts, out)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Could not write the drafts file", str(e))
            return
        # eBay only turns this file into drafts through Seller Hub's own Upload button: its
        # Feed API reads the same file but rejects the Draft action (BAF.Error.5). So CardCrop
        # puts the file in front of you and opens the page; uploading it is one drag.
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        subprocess_reveal(out)
        QDesktopServices.openUrl(QUrl("https://www.ebay.com/sh/reports/uploads"))
        box = QMessageBox(self)
        box.setWindowTitle("Drafts file ready")
        blank = [h.lstrip("*") for h in rep_["required_left_blank"]]
        box.setText(f"{rep_['rows']} card(s), with photos already on eBay, are in\n{os.path.basename(out)}\n\n"
                    "Finder is showing the file and Seller Hub's Uploads page is open: press Upload template "
                    "and choose it (or drag it in). The cards then appear in your eBay Drafts."
                    + ("\n\nColumns CardCrop could not fill: " + ", ".join(blank[:8]) if blank else ""))
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addButton(QMessageBox.Ok)
        box.exec()

    def upload(self):
        c = self.m.ebay_client()
        if not c or not c.signed_in():
            QMessageBox.information(self, "Connect eBay first", "Open Account… in the Listing tab to sign in.")
            return
        pols = {k: str(self.m.cfg.value(f"ebay_pol_{k}", "")) for k in ("fulfillment", "return", "payment")}
        zip_code = str(self.m.cfg.value("ebay_zip", ""))
        if not all(pols.values()) or not zip_code:
            QMessageBox.information(self, "Account settings needed",
                                    "Choose your policies and ship-from ZIP in Account… first.")
            return
        todo, problems = [], []
        prices = self.m._prices()
        for i, row in enumerate(self.rows):
            if self.t.item(i, 0).checkState() != Qt.Checked:
                continue
            name = os.path.basename(row["folder"])
            cond = self.t.cellWidget(i, 3).currentData()
            price = self.t.cellWidget(i, 4).value()
            missing = [w for w, ok in (("the card", row["info"]), ("a condition", cond),
                                       ("a price", price > 0), ("photos", row["photos"])) if not ok]
            if missing:
                problems.append(f"{name}: needs {', '.join(missing)}")
                continue
            prices[name] = round(price, 2)
            L = listing.build(row["info"], engine.safe_name(name), row["cent"], "", cond, price,
                              has_corner_photos(row["folder"]))
            L["store_category"] = self.m.store_category_for(name)
            L["store_category2"] = self.m.store_category_for(name, 2)
            todo.append((i, name, row["folder"], L, price))
        self.m.cfg.setValue("prices", json.dumps(prices))
        if problems:
            QMessageBox.information(self, "Some rows are not ready", "\n".join(problems) +
                                    ("\n\nThe rest will upload now." if todo else ""))
        if not todo:
            return
        self.b_up.setEnabled(False)
        self._queue = list(todo)
        self._client, self._pols, self._zip = c, pols, zip_code
        self._next()

    def _next(self):
        if not self._queue:
            self.b_up.setEnabled(True)
            self.m._ebay_status()
            return
        i, name, folder, L, price = self._queue.pop(0)
        need_loc = str(self.m.cfg.value("ebay_location_zip", "")) != self._zip
        t = EbayUploadTask(self._client, name, folder, L, price, self._pols, self._zip, self.m.out_dir, need_loc,
                           self.m.ebay_package())
        self._row = i
        # bound methods, not lambdas: Qt then delivers these on the UI thread
        t.sig.progress.connect(self._progress)
        t.sig.done.connect(self._row_done)
        if not hasattr(self.m, "net_pool"):
            self.m.net_pool = QThreadPool(self.m)
            self.m.net_pool.setMaxThreadCount(1)
        self.m.net_pool.start(t)

    def _progress(self, msg):
        i = self._row
        cell = self.t.cellWidget(i, 6)
        if not isinstance(cell, ProgressCell):
            cell = ProgressCell()
            self.t.setCellWidget(i, 6, cell)
        self.t.item(i, 6).setText("")
        cell.set(msg)

    def _end_progress(self, i):
        if isinstance(self.t.cellWidget(i, 6), ProgressCell):
            self.t.removeCellWidget(i, 6)

    def _row_done(self, _sku, res):
        i = self._row
        self._end_progress(i)
        oid, err = res
        it = self.t.item(i, 6)
        if err:
            it.setText(f"Failed: {err}  (double-click for details)")
            it.setToolTip(err)
            it.setForeground(QColor(TH.WARN))
            self.rows[i]["error"] = err
        else:
            self.m.cfg.setValue("ebay_location_zip", self._zip)
            it.setText("Uploaded, not published")
            it.setForeground(QColor(TH.OK))
            self.t.item(i, 0).setCheckState(Qt.Unchecked)
        self._next()


class IGDialog(QDialog):
    """Positions the close-up that becomes slides 2 and 3."""

    def __init__(self, parent, core_small, crop, default_crop):
        super().__init__(parent)
        self.setWindowTitle("Instagram carousel")
        self.resize(1180, 820)
        self.setStyleSheet(TH.STYLE)
        self.core, self.default_crop = core_small, default_crop
        v = QVBoxLayout(self)
        tip = QLabel("Drag the box to choose the close-up; scroll or use the slider to zoom. "
                     "The dashed line is where slide 2 swipes into slide 3.", objectName="muted")
        tip.setWordWrap(True)
        v.addWidget(tip)
        row = QHBoxLayout()
        self.view = CropView(core_small, crop, self._changed)
        row.addWidget(self.view, 2)
        right = QVBoxLayout()
        self.prev = [ImageLabel(160) for _ in range(2)]
        right.addWidget(QLabel("Slide 1", objectName="muted"))
        right.addWidget(self.prev[0], 3)
        right.addWidget(QLabel("Slides 2 and 3", objectName="muted"))
        right.addWidget(self.prev[1], 3)
        row.addLayout(right, 3)
        v.addLayout(row, 1)
        zr = QHBoxLayout()
        self.zoom_lbl, self.zoom = labeled_slider("Close-up width", 20, 100, int(round(crop[2] * 100)),
                                                  lambda x: f"{x}% of the card")
        self.zoom.valueChanged.connect(lambda x: (self.view.set_width(x / 100), self._changed()))
        zr.addWidget(self.zoom_lbl); zr.addWidget(self.zoom, 1)
        b_reset = QPushButton("Reset to default")
        b_reset.clicked.connect(self._reset)
        zr.addWidget(b_reset)
        v.addLayout(zr)
        self.c_default = QCheckBox("Use this framing as the default for new cards")
        v.addWidget(self.c_default)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save slides")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._t = QTimer(self, singleShot=True, interval=90)
        self._t.timeout.connect(self._render)
        self._render()

    def crop(self):
        return tuple(self.view.crop)

    def _reset(self):
        self.view.crop = list(self.default_crop)
        self.view._clamp()
        self.zoom.blockSignals(True); self.zoom.setValue(int(round(self.view.crop[2] * 100))); self.zoom.blockSignals(False)
        self.view.update()
        self._changed()

    def _changed(self, from_wheel=False):
        if from_wheel:
            self.zoom.blockSignals(True); self.zoom.setValue(int(round(self.view.crop[2] * 100))); self.zoom.blockSignals(False)
        self._t.start()

    def _render(self):
        s1, s2, s3 = engine.ig_slides(self.core, self.crop(), scale=0.05)
        seam = np.full((s2.shape[0], 2, 3), 255, np.uint8)        # a hairline where the swipe happens
        self.prev[0].set_q(to_qimage(s1))
        self.prev[1].set_q(to_qimage(np.ascontiguousarray(np.hstack([s2, seam, s3]))))


class ManualCardDialog(QDialog):
    """A card no database has (Carddass, Topsun, odd promos), typed in so it can still be listed."""

    GAMES = (("pokemon", "Pokémon"), ("yugioh", "Yu-Gi-Oh!"), ("onepiece", "One Piece"), ("other", "Other"))

    def __init__(self, parent, name="", info=None):
        super().__init__(parent)
        self.setWindowTitle("Enter the card yourself")
        self.setStyleSheet(TH.STYLE)
        self.resize(520, 0)
        info = info or {}
        f = QFormLayout(self)
        f.setContentsMargins(22, 20, 22, 18)
        f.setSpacing(10)
        note = QLabel("For cards in no database. CardCrop builds the title and item specifics from what you "
                      "type, and prices it from eBay listings found with these words.", objectName="small")
        note.setWordWrap(True)
        f.addRow(note)
        self.game = QComboBox()
        for k, label in self.GAMES:
            self.game.addItem(label, k)
        self.game.setCurrentIndex(max(0, self.game.findData(info.get("game", "pokemon"))))
        self.name = QLineEdit(info.get("name_en") or info.get("name") or name)
        self.name.setPlaceholderText("Charizard")
        self.set_ = QLineEdit(info.get("set_name", ""))
        self.set_.setPlaceholderText("Carddass Part 3")
        self.number = QLineEdit(info.get("number", ""))
        self.number.setPlaceholderText("As printed, if any: 6, No. 6")
        self.year = QLineEdit(str(info.get("year", "")))
        self.year.setPlaceholderText("1997")
        self.rarity = QLineEdit(info.get("rarity", ""))
        self.rarity.setPlaceholderText("Prism, Holo, Promo… or leave empty")
        self.maker = QLineEdit(info.get("maker", ""))
        self.maker.setPlaceholderText("Bandai, Topsun… empty for the game's usual maker")
        self.lang = QComboBox()
        for k, label in identify.LANGS.items():
            self.lang.addItem(label, k)
        self.lang.setCurrentIndex(max(0, self.lang.findData(info.get("language", "en"))))
        for label, w in (("Game", self.game), ("Name", self.name), ("Set or series", self.set_),
                         ("Number", self.number), ("Year", self.year), ("Rarity or finish", self.rarity),
                         ("Made by", self.maker), ("Language", self.lang)):
            f.addRow(label, w)
        self.preview = QLabel("", objectName="mono")
        self.preview.setWordWrap(True)
        f.addRow("Title", self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setText("Use this card")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        for w in (self.name, self.set_, self.number, self.year, self.rarity, self.maker):
            w.textChanged.connect(self._update)
        self.game.currentIndexChanged.connect(self._update)
        self.lang.currentIndexChanged.connect(self._update)
        self._update()

    def card(self):
        return identify.manual_card(self.name.text(), self.set_.text(), self.number.text(), self.year.text(),
                                    self.rarity.text(), self.lang.currentData(), self.game.currentData(),
                                    self.maker.text())

    def _update(self, *_a):
        ok = bool(self.name.text().strip())
        self.ok.setEnabled(ok)
        self.preview.setText(listing.make_title(self.card().to_dict()) if ok else "A name is needed")


class IdentifyDialog(QDialog):
    """Search by collector number ('4/102') or name, then pick the exact card."""

    def __init__(self, parent, db, query, lang, results=None, photo=None, edition="", current=None):
        super().__init__(parent)
        self.photo, self.edition, self.current = photo, edition, current
        self.setWindowTitle("Identify card")
        self.resize(760, 760)
        self.db, self.results, self.choice = db, [], None
        self.setStyleSheet(TH.STYLE)
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.q = QLineEdit(query)
        self.q.setPlaceholderText("Name, number or both: lugia 185, 185/195, charizard ex")

        self.q.returnPressed.connect(self.search)
        self.lang = QComboBox()
        for k, label in identify.LANGS.items():
            self.lang.addItem(label, k)
        self.lang.setCurrentIndex(max(0, list(identify.LANGS).index(lang) if lang in identify.LANGS else 0))
        self.game = QComboBox()
        for k, label in identify.GAMES.items():
            self.game.addItem(label, k)
        g = str(QSettings("CardCrop", "CardCrop").value("id_game", "pokemon"))
        self.game.setCurrentIndex(max(0, list(identify.GAMES).index(g) if g in identify.GAMES else 0))
        self.game.currentIndexChanged.connect(self._game_changed)
        go = QPushButton("Search")
        go.setAutoDefault(False)
        go.clicked.connect(self.search)
        row.addWidget(self.game)
        row.addWidget(self.q, 1)
        row.addWidget(self.lang)
        row.addWidget(go)
        v.addLayout(row)
        self.status = QLabel("", objectName="muted")
        v.addWidget(self.status)
        self.list = QListWidget()
        from PySide6.QtCore import QSize
        self.list.setIconSize(QSize(120, 168))
        self._game_changed(0, initial=True)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        v.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Use this card")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        b_man = bb.addButton("Not listed? Enter it yourself…", QDialogButtonBox.ResetRole)
        b_man.setAutoDefault(False)
        b_man.setToolTip("For cards in no database, like Carddass or Topsun: type the name, set, number and "
                         "year, and it lists like any other card")
        b_man.clicked.connect(self.enter_manually)
        v.addWidget(bb)
        self.pool = QThreadPool.globalInstance()
        if results:
            self.show_results(results)
        elif query:
            QTimer.singleShot(0, self.search)

    def search(self):
        q = self.q.text().strip()
        if not q:
            return
        self.status.setText("Searching…")
        self.list.clear()
        QSettings("CardCrop", "CardCrop").setValue("id_game", self.game.currentData())
        t = IdentifyTask(self.db, None, self.photo, self.lang.currentData(), query=q, game=self.game.currentData())
        t.edition = self.edition
        t.sig.done.connect(self._searched)      # bound method: delivered on the UI thread
        self.pool.start(t)

    def _game_changed(self, _i, initial=False):
        g = self.game.currentData()
        self.lang.setVisible(g == "pokemon")       # the Yu-Gi-Oh! and One Piece databases are English
        self.q.setPlaceholderText({"yugioh": "Name, set code or both: dark magician, LOB-EN005",
                                   "onepiece": "Name, card code or both: zoro, OP01-001, luffy op05"}.get(
            g, "Name, number or both: lugia 185, 185/195, charizard ex"))
        if self.q.text().strip() and not initial:
            self.search()

    def _searched(self, _job, res):
        _, results, err = res
        if err:
            self.status.setText(f"Search failed: {err}. Check the internet connection.")
            return
        self.show_results(results)

    def show_results(self, results):
        self.results = results
        self.list.clear()
        self.status.setText(f"{len(results)} match(es)" if results else
                            "No matches. Try fewer words, or just the name and the number or code")
        if len(results) > 1 and results[0].game == "yugioh" and len({r.number for r in results}) == 1:
            self.status.setText(f"{results[0].number} was printed in {len(results)} rarities, with the same art. "
                                "Pick yours by the foil on the name and the art")
        elif len(results) > 1 and results[0].match:
            self.status.setText(f"{len(results)} versions, closest to your photo first")
        for i, info in enumerate(results):
            like = f"  ·  {max(0, int(info.match * 100))}% like your photo" if info.match else ""
            it = QListWidgetItem(info.label() + like)
            self.list.addItem(it)
            t = ThumbTask(self.db, info, i)
            t.sig.done.connect(self._thumb)
            self.pool.start(t)
        if results:
            self.list.setCurrentRow(0)

    def _thumb(self, row, data):
        if data and row < self.list.count():
            pm = QPixmap()
            pm.loadFromData(data)
            from PySide6.QtGui import QIcon
            self.list.item(row).setIcon(QIcon(pm))

    def enter_manually(self):
        cur = self.current if (self.current or {}).get("id", "").startswith("manual:") else None
        d = ManualCardDialog(self, self.q.text().strip() if not cur else "", cur)
        if d.exec() == QDialog.Accepted:
            self.choice = d.card()
            QDialog.accept(self)

    def keyPressEvent(self, e):
        # Enter in the search bar searches; it never picks a card or closes the window
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.focusWidget() is self.q:
            e.accept()
            return
        super().keyPressEvent(e)

    def accept(self):
        if self.focusWidget() is self.q:        # Enter in the search bar searches, and only that
            return
        r = self.list.currentRow()
        if 0 <= r < len(self.results):
            self.choice = self.results[r]
        super().accept()


class CalibrateDialog(QDialog):
    def __init__(self, main, first=False):
        super().__init__(main)
        import calibrate
        self.m = main
        self.setWindowTitle("Calibrate condition reports")
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setSpacing(12)
        t = QLabel("Calibrate condition reports")
        t.setStyleSheet(f"font-size:{TH.BASE_PT + 8}pt; font-weight:600;")
        v.addWidget(t)
        intro = QLabel(
            ("Before the first report, CardCrop learns how you grade. " if first else "")
            + "Every card you have already given a condition is measured: your eBay listings, live and sold "
            "in the last 60 days, and any exported folders below whose cards have a condition set. The "
            "scoring is then fitted until its bands match yours, and checked on cards it was not fitted on. "
            f"It needs at least {calibrate.MIN_CARDS} graded cards, {calibrate.MIN_LOWER} or more of them below "
            "Near Mint. Your own exports are measured at full size when a listing's SKU matches one.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        v.addWidget(QLabel("FOLDERS TO SEARCH FOR YOUR EXPORTS", objectName="mono"))
        self.lst = QListWidget()
        self.lst.setMaximumHeight(120)
        saved = self.m.cfg.value("calib_folders", []) or []
        saved = [saved] if isinstance(saved, str) else list(saved)
        folders = [self.m.out_dir] + [f for f in saved if f]
        for f in dict.fromkeys(folders):
            self.lst.addItem(f)
        v.addWidget(self.lst)
        row = QHBoxLayout()
        b_add = QPushButton("Add folder…")
        b_add.clicked.connect(self._add)
        b_rm = QPushButton("Remove")
        b_rm.clicked.connect(lambda: [self.lst.takeItem(self.lst.row(i)) for i in self.lst.selectedItems()])
        row.addWidget(b_add)
        row.addWidget(b_rm)
        row.addStretch(1)
        v.addLayout(row)
        self.use_ebay = QCheckBox("Use my eBay listings (the condition each one was listed with)")
        self.use_ebay.setChecked(True)
        v.addWidget(self.use_ebay)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = QLabel(calibrate.summary() if calibrate.load_model() else "")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.misses = QListWidget()
        self.misses.hide()
        v.addWidget(self.misses, 1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.b_close = QPushButton("Close")
        self.b_close.clicked.connect(self._close)
        self.b_go = QPushButton("Start", objectName="primary")
        self.b_go.clicked.connect(self._start)
        btns.addWidget(self.b_close)
        btns.addWidget(self.b_go)
        v.addLayout(btns)
        self.task = None

    def _add(self):
        d = QFileDialog.getExistingDirectory(self, "A folder of exported cards (folders of folders are fine)")
        if d:
            self.lst.addItem(d)

    def _folders(self):
        return [self.lst.item(i).text() for i in range(self.lst.count())]

    def _start(self):
        folders = self._folders()
        self.m.cfg.setValue("calib_folders", [f for f in folders if f != self.m.out_dir])
        client = None
        if self.use_ebay.isChecked():
            client = self.m.ebay_client()
            if client is None or not client.signed_in():
                self.m.notice("Connect eBay in Settings > eBay to use your listings, or untick it.", "warn")
                return
        store = self.m.store_page.data if client is not None and hasattr(self.m, "store_page") else None
        self.task = CalibrateTask(client, self.m.db, folders, store)
        self.task.sig.progress.connect(self._progress)
        self.task.sig.done.connect(self._done)
        self.b_go.setEnabled(False)
        self.b_close.setText("Stop")
        self.bar.show()
        self.misses.hide()
        QThreadPool.globalInstance().start(self.task)

    def _progress(self, i, n, text):
        self.bar.setRange(0, max(0, n))
        self.bar.setValue(i)
        self.status.setText(text)

    def _done(self, model, err, problems):
        import calibrate
        self.task = None
        self.bar.hide()
        self.b_go.setEnabled(True)
        self.b_go.setText("Calibrate again")
        self.b_close.setText("Close")
        if err:
            self.status.setText(err + (f"  ({len(problems)} cards could not be read.)" if problems else ""))
            return
        if model is None:
            self.status.setText("Stopped. Cards measured so far are kept for next time.")
            return
        self.status.setText(calibrate.summary(model)
                            + (f" {len(problems)} cards could not be read." if problems else ""))
        if model["misses"]:
            self.misses.clear()
            self.misses.addItem(f"Where it disagreed with you ({len(model['misses'])}):")
            for x in model["misses"]:
                self.misses.addItem(f"{x['title'][:70]}   you: {x['yours']}   it: {x['model']}")
            self.misses.show()

    def _close(self):
        if self.task is not None:
            self.task.stop = True
            self.status.setText("Stopping after this card…")
            return
        self.accept()

    def closeEvent(self, e):
        if self.task is not None:
            self.task.stop = True
        super().closeEvent(e)


class ArrangeView(QWidget):
    """The card flat, with your PNG layers: drag the chosen layer to move it, scroll to resize it."""

    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.pm = None
        self.win = None
        self._drag = None
        self.setMinimumSize(420, 560)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)

    def _rect(self):
        if self.pm is None:
            return QRectF()
        k = min(self.width() / self.pm.width(), self.height() / self.pm.height())
        w, h = self.pm.width() * k, self.pm.height() * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#141416"))
        if self.pm is None:
            return
        r = self._rect()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(r.toRect(), self.pm)
        if self.win:
            k = r.width() / self.pm.width()
            x0, y0, x1, y1 = self.win
            p.setPen(QPen(QColor(ACCENT), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(r.x() + x0 * k, r.y() + y0 * k, (x1 - x0) * k, (y1 - y0) * k))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is None or not self.win or self.pm is None:
            return
        k = self._rect().width() / self.pm.width()
        uw, uh = self.dlg.units()
        d = e.position() - self._drag
        self._drag = e.position()
        self.dlg.nudge(d.x() / (k * uw), d.y() / (k * uh))

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, e):
        step = e.angleDelta().y() or e.angleDelta().x()
        self.dlg.zoom(1.04 if step > 0 else 1 / 1.04)


class GroupDialog(QDialog):
    """Pick the cards to show together, and how they move."""

    def __init__(self, parent, names, older, chosen, preset, least=2, title="Several cards together",
                 ok_text="Show them together", show_preset=True):
        super().__init__(parent)
        import card3d
        self.least = least
        self.setWindowTitle(title)
        self.setStyleSheet(TH.STYLE)
        self.resize(520, 680)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)
        top = QLabel(f"Tick {least} to {card3d.GROUP_MAX} cards. They appear in the order you tick them.",
                     objectName="small")
        top.setWordWrap(True)
        v.addWidget(top)
        sel = QHBoxLayout()
        for label, on in (("Select all", True), ("Select none", False)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, o=on: self._tick_all(o))
            sel.addWidget(b)
        sel.addStretch(1)
        v.addLayout(sel)
        self.list = QListWidget()
        self.order = [n for n in chosen if n in names or n in older]
        for group_, names_ in (("This batch", names), ("Exported earlier", older)):
            if not names_:
                continue
            hd = QListWidgetItem(group_)
            hd.setFlags(Qt.NoItemFlags)
            self.list.addItem(hd)
            for n in names_:
                it = QListWidgetItem(n)
                it.setData(Qt.UserRole, n)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                it.setCheckState(Qt.Checked if n in self.order else Qt.Unchecked)
                self.list.addItem(it)
        self.list.itemChanged.connect(self._ticked)
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Animation"))
        self.preset = QComboBox()
        for k, (label, _fn) in card3d.GROUP_PRESETS.items():
            self.preset.addItem(label, k)
        self.preset.setCurrentIndex(max(0, self.preset.findData(preset)))
        row.addWidget(self.preset, 1)
        v.addLayout(row)
        if not show_preset:
            for i in range(row.count()):
                if row.itemAt(i).widget():
                    row.itemAt(i).widget().hide()
        self.count = QLabel("", objectName="small")
        v.addWidget(self.count)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setText(ok_text)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._ticked()

    def _tick_all(self, on):
        """Tick every card (up to the most that can be shown together), or none."""
        import card3d
        self.list.blockSignals(True)
        if not on:
            self.order = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            n = it.data(Qt.UserRole)
            if n is None:
                continue
            if on and n not in self.order and len(self.order) < card3d.GROUP_MAX:
                self.order.append(n)
            it.setCheckState(Qt.Checked if n in self.order else Qt.Unchecked)
        self.list.blockSignals(False)
        self._ticked()

    def _ticked(self, it=None):
        import card3d
        if it is not None:
            n = it.data(Qt.UserRole)
            if it.checkState() == Qt.Checked and n not in self.order:
                if len(self.order) >= card3d.GROUP_MAX:
                    self.list.blockSignals(True)
                    it.setCheckState(Qt.Unchecked)
                    self.list.blockSignals(False)
                else:
                    self.order.append(n)
            elif it.checkState() != Qt.Checked and n in self.order:
                self.order.remove(n)
        k = len(self.order)
        self.count.setText(f"{k} ticked" + ("" if k >= self.least else f", tick at least {self.least}"))
        self.ok.setEnabled(k >= self.least)


class ArrangeDialog(QDialog):
    """Place your subject and backdrop by hand: drag, scroll, arrow keys, or type exact numbers."""

    def __init__(self, parent, folder, fit, order=None):
        super().__init__(parent)
        import layers
        self.layers, self.folder = layers, folder
        self.fit = {r: list(v) for r, v in fit.items()}
        self.order = list(order or [])
        self.files = layers.find_layer_files(folder)
        self.setWindowTitle("Arrange your layers")
        self.setStyleSheet(TH.STYLE)
        self.resize(760, 860)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        top = QHBoxLayout()
        self.role = "subject" if "subject" in self.files else ("backdrop" if "backdrop" in self.files else "")
        self.role_lbl = QLabel("", objectName="display")
        top.addWidget(self.role_lbl)
        top.addStretch(1)
        hint = QLabel("Pick a layer on the right · drag to move · scroll to resize · arrow keys nudge "
                      "(Shift for bigger steps)", objectName="small")
        top.addWidget(hint)
        v.addLayout(top)
        mid = QHBoxLayout()
        mid.setSpacing(12)
        self.view = ArrangeView(self)
        mid.addWidget(self.view, 1)
        side = QVBoxLayout()
        side.setSpacing(6)
        side.addWidget(QLabel("Layers, top to bottom: click one to move it, drag to restack", objectName="small"))
        self.stack = QListWidget()
        self.stack.setDragDropMode(QAbstractItemView.InternalMove)
        self.stack.setFixedWidth(240)
        self.stack.model().rowsMoved.connect(lambda *_a: self._order_changed())
        self.stack.currentRowChanged.connect(self._row_picked)
        side.addWidget(self.stack, 1)
        ud = QHBoxLayout()
        for txt, d_ in (("Up", -1), ("Down", 1)):
            b = QPushButton(txt)
            b.clicked.connect(lambda _=False, d_=d_: self._move(d_))
            ud.addWidget(b)
        side.addLayout(ud)
        bg_lbl = QLabel("Backdrop is always at the bottom, behind everything", objectName="small")
        bg_lbl.setWordWrap(True)
        bg_lbl.setFixedWidth(220)
        side.addWidget(bg_lbl)
        mid.addLayout(side)
        v.addLayout(mid, 1)
        nums = QHBoxLayout()
        self.n_size, self.n_x, self.n_y = QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox()
        for w_, lo, hi, suf, step in ((self.n_size, 10, 600, "%", 1), (self.n_x, -150, 150, "%", 0.5),
                                      (self.n_y, -150, 150, "%", 0.5)):
            w_.setRange(lo, hi)
            w_.setSuffix(suf)
            w_.setSingleStep(step)
            w_.setDecimals(1)
            w_.valueChanged.connect(self._typed)
        for label, w_ in (("Size", self.n_size), ("Across", self.n_x), ("Down", self.n_y)):
            nums.addWidget(QLabel(label, objectName="small"))
            nums.addWidget(w_)
        nums.addStretch(1)
        b_reset = QPushButton("Reset this layer")
        b_reset.clicked.connect(self.reset)
        nums.addWidget(b_reset)
        v.addLayout(nums)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Use this layout")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._timer = QTimer(self, singleShot=True, interval=16)
        self._timer.timeout.connect(self.render)
        self._sync()
        self.render()
        self._fill_stack()

    def _label(self, item):
        return {"subject": "Subject", "backdrop": "Backdrop"}.get(item, f"Frame · {item}")

    def _fill_stack(self):
        self.stack.blockSignals(True)
        self.stack.clear()
        for item in self.order + (["backdrop"] if "backdrop" in self.files else []):
            it = QListWidgetItem(self._label(item))
            it.setData(Qt.UserRole, item)
            if item == "backdrop":
                it.setFlags(it.flags() & ~Qt.ItemIsDragEnabled & ~Qt.ItemIsDropEnabled)
            self.stack.addItem(it)
            if item == self.role:
                self.stack.setCurrentItem(it)
        self.stack.blockSignals(False)
        self._role_text()

    def _row_picked(self, r):
        it = self.stack.item(r)
        if it is not None:
            self.role = it.data(Qt.UserRole)
            self._sync()
            self._role_text()

    def _role_text(self):
        self.role_lbl.setText("Moving: " + self._label(self.role))

    def _order_changed(self):
        items = [self.stack.item(i).data(Qt.UserRole) for i in range(self.stack.count())]
        self.order = [x for x in items if x != "backdrop"]
        if items and items[-1] != "backdrop" and "backdrop" in items:
            self._fill_stack()                         # the backdrop goes back to the bottom
        self.render()

    def units(self):
        """What one step of position is measured in: the art window for the subject and backdrop,
        the whole card for a frame file."""
        if self.role in ("subject", "backdrop") and self.view.win:
            x0, y0, x1, y1 = self.view.win
            return x1 - x0, y1 - y0
        pm = self.view.pm
        return (pm.width(), pm.height()) if pm is not None else (1, 1)

    def _move(self, d):
        r = self.stack.currentRow()
        last = self.stack.count() - (1 if "backdrop" in self.files else 0)
        if r < 0 or not 0 <= r + d < last or r >= last:
            return
        it = self.stack.takeItem(r)
        self.stack.insertItem(r + d, it)
        self.stack.setCurrentRow(r + d)
        self._order_changed()

    def cur(self):
        return self.fit.setdefault(self.role, [1.0, 0.0, 0.0])


    def _sync(self):
        sc, dx, dy = self.cur()
        for w_, val in ((self.n_size, sc * 100), (self.n_x, dx * 100), (self.n_y, dy * 100)):
            w_.blockSignals(True)
            w_.setValue(val)
            w_.blockSignals(False)

    def _typed(self, *_a):
        c = self.cur()
        c[0], c[1], c[2] = self.n_size.value() / 100, self.n_x.value() / 100, self.n_y.value() / 100
        self._timer.start()

    def nudge(self, dx, dy):
        c = self.cur()
        c[1] += dx
        c[2] += dy
        self._sync()
        self._timer.start()

    def zoom(self, f):
        c = self.cur()
        c[0] = max(0.1, min(6.0, c[0] * f))
        self._sync()
        self._timer.start()

    def reset(self):
        self.fit[self.role] = [1.0, 0.0, 0.0]
        self._sync()
        self.render()

    def keyPressEvent(self, e):
        st = 0.02 if e.modifiers() & Qt.ShiftModifier else 0.004
        keys = {Qt.Key_Left: (-st, 0), Qt.Key_Right: (st, 0), Qt.Key_Up: (0, -st), Qt.Key_Down: (0, st)}
        if e.key() in keys and not isinstance(self.focusWidget(), QDoubleSpinBox):
            self.nudge(*keys[e.key()])
            return
        if e.key() in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom(1.02)
            return
        if e.key() == Qt.Key_Minus:
            self.zoom(1 / 1.02)
            return
        super().keyPressEvent(e)

    def render(self):
        try:
            d = self.layers.from_pngs(self.folder, {r: tuple(v) for r, v in self.fit.items()}, size=1000,
                                      order=self.order)
            self.order = d.get("order", self.order)
        except Exception as e:  # noqa: BLE001
            self.setWindowTitle(f"Arrange your layers: {e}")
            return
        # outside the card's rounded corners stays see-through, as on the real card
        rgba = np.ascontiguousarray(np.dstack([cv2.cvtColor(d["img"], cv2.COLOR_BGR2RGB), d["shape"]]))
        qi = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.shape[1] * 4, QImage.Format_RGBA8888).copy()
        self.view.pm = QPixmap.fromImage(qi)
        self.view.win = d.get("window")
        self.view.update()


class _SideTile(QWidget):
    """One photo in Fronts and backs: click to switch front and back, drag onto another to pair them."""

    def __init__(self, dlg, i, pm):
        super().__init__()
        self.dlg, self.i = dlg, i
        self.setFixedSize(124, 196)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.pm = pm
        self._press = None
        self._hot = False

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or not self.dlg.editable:
            return
        if (e.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDrag
        self._press = None
        md = QMimeData()
        md.setText(f"cardcrop-tile:{self.i}")
        dr = QDrag(self)
        dr.setMimeData(md)
        if self.pm is not None:
            pm = self.pm.scaled(86, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dr.setPixmap(pm)
            dr.setHotSpot(pm.rect().center())
        self.dlg.drag_started(self.i)
        try:
            dr.exec(Qt.MoveAction)
        finally:
            self.dlg.drag_ended()

    def contextMenuEvent(self, e):
        if self.dlg.editable:
            self.dlg.tile_menu(self.i, e.globalPos())

    def mouseReleaseEvent(self, e):
        if self._press is not None and self.dlg.editable:
            self.dlg.flip(self.i)
        self._press = None

    def dragEnterEvent(self, e):
        t = e.mimeData().text()
        if t.startswith("cardcrop-tile:") and int(t.split(":")[1]) != self.i:
            self._hot = True
            self.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._hot = False
        self.update()

    def dropEvent(self, e):
        self._hot = False
        self.dlg.pair(int(e.mimeData().text().split(":")[1]), self.i)
        e.acceptProposedAction()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.dlg.dragging == self.i:
            p.setOpacity(0.3)                     # lifted: the picture travels with the pointer
        sd = self.dlg.sides[self.i]
        front = sd == "front"
        r = QRectF(1.5, 1.5, self.width() - 3, self.height() - 3)
        p.setBrush(QColor(TH.T["island"]))
        p.setPen(QPen(QColor(LIME if (front or self._hot) else TH.T["line"]), 3 if (front or self._hot) else 2))
        p.drawRoundedRect(r, 12, 12)
        if self.pm is not None:
            pm = self.pm.scaled(86, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(int((self.width() - pm.width() / pm.devicePixelRatio()) / 2), 10, pm)
        own = self.dlg.own.get(self.i)
        p.setPen(QColor(TH.T["text"] if front else (TH.T["muted"] if own is not None else TH.T["need"])))
        f = p.font()
        f.setBold(front)
        p.setFont(f)
        head = f"{self.i + 1}  ·  " + ("FRONT" if front else (f"back of {own + 1}" if own is not None else "no front"))
        p.drawText(QRectF(4, 136, self.width() - 8, 20), Qt.AlignCenter, head)
        f.setBold(False)
        f.setPointSizeF(max(7.0, f.pointSizeF() - 2))
        p.setFont(f)
        p.setPen(QColor(TH.T["muted"]))
        p.drawText(QRectF(6, 156, self.width() - 12, 34), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                   self.dlg.caption(self.i))
        p.end()


class SidesDialog(QDialog):
    """Every photo still to export as a tile, in shooting order. Click one to make it a front or a back,
    drag a back onto its front to pair them by hand; Find backs marks backs by look. Apply pairs every
    back with its front, then the window stays open while the fronts are read, naming each tile."""

    def __init__(self, main, jobs, thumb_pm):
        super().__init__(main)
        from PySide6.QtWidgets import QScrollArea
        self.m, self.jobs = main, jobs
        self.sides = [j.side if j.side in ("front", "back") else "front" for j in jobs]
        # pairs as they stand: a back already tied to a front in this list stays with it
        idx = {id(j): k for k, j in enumerate(jobs)}
        self.manual = {k: idx[id(j._pair_of)] for k, j in enumerate(jobs)
                       if getattr(j, "_pair_of", None) is not None and id(j._pair_of) in idx}
        self.own = engine.pair_backs(self.sides, self.manual)
        self.editable, self.reading = True, []
        self.dragging = None
        self.setWindowTitle("Fronts and backs")
        self.setStyleSheet(TH.STYLE)
        self.resize(1170, 820)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(12)
        top = QLabel("Click a photo to switch it between front and back. Drag a back onto its front to pair them "
                     "(hold it near the top or bottom edge to scroll), or right-click a back and pick its front. "
                     "Any other back belongs to the nearest front before it. Apply names each back after its front "
                     "and reads the fronts again.", objectName="small")
        top.setWordWrap(True)
        v.addWidget(top)
        bar = QHBoxLayout()
        self.tools = []
        for label, tip, fn in (("Find backs", "Mark backs by look: a game's backs are one design, so they match "
                                "each other", self.find_backs),
                               ("Alternate", "Front, back, front, back from the first photo", self.alternate),
                               ("All fronts", "Every photo a front, for cards shot without backs", self.all_fronts),
                               ("Clear pairs", "Forget the pairs made by hand: every back goes with the front "
                                "before it", self.clear_pairs)):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
            self.tools.append(b)
        bar.addStretch(1)
        self.count = QLabel("", objectName="small")
        bar.addWidget(self.count)
        v.addLayout(bar)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        g = QGridLayout(body)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(10)
        self.tiles = []
        cols = 8
        for i, j in enumerate(jobs):
            t = _SideTile(self, i, thumb_pm(j))
            t.setToolTip(j.stem)
            g.addWidget(t, i // cols, i % cols)
            self.tiles.append(t)
        g.setRowStretch(len(jobs) // cols + 1, 1)
        g.setColumnStretch(cols, 1)
        sa.setWidget(body)
        v.addWidget(sa, 1)
        self.sa = sa
        # while a photo is dragged, the list scrolls by itself when the pointer nears its top or bottom
        self.edge = QTimer(self, interval=30)
        self.edge.timeout.connect(self._edge_scroll)
        self.reread = QCheckBox("Read every front again, even ones already identified")
        self.reread.setToolTip("Off: a front that was already a front and identified keeps its card. "
                               "Names you typed yourself are always kept")
        v.addWidget(self.reread)
        foot = QHBoxLayout()
        self.status = QLabel("", objectName="small")
        foot.addWidget(self.status, 1)
        self.b_cancel = QPushButton("Cancel")
        self.b_cancel.clicked.connect(self.reject)
        foot.addWidget(self.b_cancel)
        self.b_ok = QPushButton("Apply and identify", objectName="primary")
        self.b_ok.clicked.connect(self.apply)
        foot.addWidget(self.b_ok)
        v.addLayout(foot)
        self.timer = QTimer(self, interval=400)
        self.timer.timeout.connect(self._poll)
        self._draw()

    # ---------- what the tiles say
    def caption(self, i):
        j = self.jobs[i]
        if self.reading and j in self.reading and getattr(j, "id_bg", False):
            return "reading…"
        info = j.card_info or {}
        if info:
            return f"{info.get('name_en') or info.get('name', '')} {info.get('number', '')}".strip()
        if j.card_name.strip():
            return j.card_name.strip()
        if self.reading and j in self.reading:
            return "pick the card" if getattr(j, "id_results", None) else "not read"
        return ""

    def _draw(self):
        self.own = engine.pair_backs(self.sides, self.manual)
        for t in self.tiles:
            t.update()
        nf = self.sides.count("front")
        nb = len(self.sides) - nf
        lone = nb - len(self.own)
        self.count.setText(f"{nf} front{'s' if nf != 1 else ''} · {nb} back{'s' if nb != 1 else ''}"
                           + (f" · {lone} without a front" if lone else ""))

    # ---------- edits
    def flip(self, i):
        self.sides[i] = "back" if self.sides[i] == "front" else "front"
        self.manual = {b: f for b, f in self.manual.items() if i not in (b, f)}
        self._draw()

    def pair(self, src, dst):
        """Dragged onto another photo: the one dropped on is the front, the dragged one its back."""
        self.sides[dst], self.sides[src] = "front", "back"
        self.manual = {b: f for b, f in self.manual.items() if b != src and f != dst and b != dst}
        self.manual[src] = dst
        self._draw()

    def drag_started(self, i):
        self.dragging = i
        self.tiles[i].update()
        self.edge.start()

    def drag_ended(self):
        i, self.dragging = self.dragging, None
        self.edge.stop()
        if i is not None:
            self.tiles[i].update()

    def _edge_scroll(self):
        from PySide6.QtGui import QCursor
        vp = self.sa.viewport()
        y = vp.mapFromGlobal(QCursor.pos()).y()
        zone = 70
        sb = self.sa.verticalScrollBar()
        if y < zone:
            sb.setValue(sb.value() - max(4, int((zone - y) / 3)))
        elif y > vp.height() - zone:
            sb.setValue(sb.value() + max(4, int((y - vp.height() + zone) / 3)))

    def tile_menu(self, i, at):
        """Right-click: make a photo a front, or the back of any front, wherever that front is in the list."""
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        if self.sides[i] == "back":
            m.addAction("Make this a front", lambda: self.flip(i))
        else:
            m.addAction("Make this a back", lambda: self.flip(i))
        sub_ = m.addMenu("Make this the back of")
        for k, sd in enumerate(self.sides):
            if k == i or sd != "front":
                continue
            cap = self.caption(k)
            sub_.addAction(f"{k + 1}" + (f"  ·  {cap}" if cap else ""), lambda k_=k: self.pair(i, k_))
        if sub_.isEmpty():
            sub_.setEnabled(False)
        if i in self.manual:
            m.addAction("Unpair", lambda: self._unpair(i))
        m.exec(at)

    def _unpair(self, i):
        self.manual.pop(i, None)
        self._draw()

    def clear_pairs(self):
        self.manual = {}
        self._draw()

    def find_backs(self):
        thumbs = [getattr(j, "thumb_base", None) for j in self.jobs]
        self.sides = ["back" if b else "front" for b in engine.guess_backs(thumbs)]
        self.manual = {}
        self._draw()

    def alternate(self):
        self.sides = ["front" if i % 2 == 0 else "back" for i in range(len(self.jobs))]
        self.manual = {}
        self._draw()

    def all_fronts(self):
        self.sides = ["front"] * len(self.jobs)
        self.manual = {}
        self._draw()

    # ---------- apply, then watch the fronts being read
    def apply(self):
        if not self.editable:
            self.accept()
            return
        self.editable = False
        for w in self.tools + [self.reread, self.b_cancel]:
            w.setEnabled(False)
        self.b_ok.setEnabled(False)
        self.reading = list(self.m.apply_sides(self.jobs, self.sides, self.reread.isChecked(), self.manual) or [])
        self._poll()
        if self.reading:
            self.timer.start()

    def _poll(self):
        busy = sum(1 for j in self.reading if getattr(j, "id_bg", False))
        done_ = len(self.reading) - busy
        for t in self.tiles:
            t.update()
        if busy:
            self.status.setText(f"Reading the fronts: {done_} of {len(self.reading)} done. You can keep this "
                                "open; it fills in as each card is named.")
            self.b_ok.setText(f"Reading {done_ + 1} of {len(self.reading)}…")
            return
        self.timer.stop()
        named = sum(1 for j in self.reading if j.card_info)
        if self.reading:
            left = len(self.reading) - named
            self.status.setText(f"Done: {named} of {len(self.reading)} fronts named, and their backs with them."
                                + (f" {left} need you: open them and press I to pick the card." if left else ""))
        else:
            self.status.setText("Done: fronts and backs set, every front already had its card.")
        self.b_ok.setText("Close")
        self.b_ok.setEnabled(True)

    def reject(self):
        if not self.editable and self.timer.isActive():
            return                                   # still reading: the window stays until it is done
        super().reject()

    def closeEvent(self, e):
        if not self.editable and self.timer.isActive():
            e.ignore()
            return
        super().closeEvent(e)


# names from the other parts, bound once every part has loaded
from ui_base import ACCENT, LIME, subprocess_reveal, to_qimage  # noqa: E402
from ui_editor import CropView  # noqa: E402
from ui_tasks import CalibrateTask, EbayPhotosTask, EbayUploadTask, FolderIdTask, IdentifyTask, PriceTask, ThumbTask, folder_listing_info, looks_exported  # noqa: E402
from ui_widgets import ImageLabel, PriceBox, ProgressCell, has_corner_photos, labeled_slider, tick_buttons  # noqa: E402
