# Copyright (c) 2016 Yubico AB
# All rights reserved.
#
#   Redistribution and use in source and binary forms, with or
#   without modification, are permitted provided that the following
#   conditions are met:
#
#    1. Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#    2. Redistributions in binary form must reproduce the above
#       copyright notice, this list of conditions and the following
#       disclaimer in the documentation and/or other materials provided
#       with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from __future__ import absolute_import, print_function

from PySide import QtGui, QtCore
from binascii import a2b_hex, b2a_hex
from base64 import b32decode
from ykman.yubicommon import qt
from .. import messages as m
from ...util import modhex_decode, modhex_encode
from ...driver_otp import YkpersError
import re
import os
import struct

class B32Validator(QtGui.QValidator):

    def __init__(self, parent=None):
        super(B32Validator, self).__init__(parent)
        self.partial = re.compile(r'^[ a-z2-7]+$', re.IGNORECASE)

    def fixup(self, value):
        try:
            unpadded = value.upper().rstrip('=').replace(' ', '')
            return b32decode(unpadded + '=' * (-len(unpadded) % 8))
        except:
            return None

    def validate(self, value, pos):
        try:
            if self.fixup(value) is not None:
                return QtGui.QValidator.Acceptable
        except:
            pass
        if self.partial.match(value):
            return QtGui.QValidator.Intermediate
        return QtGui.QValidator.Invalid


class HexValidator(QtGui.QValidator):
    partial_pattern = r'^[ a-f0-9]*$'

    def __init__(self, min_bytes=0, max_bytes=None, parent=None):
        super(HexValidator, self).__init__(parent)
        self.partial = re.compile(self.partial_pattern, re.IGNORECASE)
        self._min = min_bytes
        self._max = max_bytes if max_bytes is not None else float('inf')

    def fixup(self, value):
        try:
            return a2b_hex(value.replace(' ', ''))
        except:
            return None

    def validate(self, value, pos):
        try:
            fixed = self.fixup(value)
            if fixed is not None and self._min <= len(fixed) <= self._max:
                return QtGui.QValidator.Acceptable
        except:
            pass

        if self.partial.match(value) and \
                (len(value.replace(' ', '')) + 1) / 2 <= self._max:
            return QtGui.QValidator.Intermediate

        return QtGui.QValidator.Invalid


class ModhexValidator(HexValidator):
    partial_pattern = r'^[cbdefghijklnrtuv]+$'

    def __init__(self, min_bytes=0, max_bytes=None, parent=None):
        super(ModhexValidator, self).__init__(min_bytes, max_bytes, parent)

    def fixup(self, value):
        try:
            return modhex_decode(value.replace(' ', ''))
        except:
            return None


class _SlotStatus(QtGui.QWidget):

    def __init__(self, parent=None):
        super(_SlotStatus, self).__init__(parent)

        layout = QtGui.QGridLayout(self)
        layout.addWidget(QtGui.QLabel('<h2>' + m.slot_configuration + '</h2>'), 0, 0, 1, 4)

        layout.addWidget(QtGui.QLabel(m.slot_1), 1, 0)
        self._slot1_lbs = (QtGui.QLabel(), QtGui.QPushButton(m.configure), QtGui.QPushButton(m.erase))
        self._slot1_lbs[1].clicked.connect(lambda: self.parent().configure(1))
        self._slot1_lbs[2].setVisible(False)
        self._slot1_lbs[2].clicked.connect(lambda: self.parent().erase(1))
        layout.addWidget(self._slot1_lbs[0], 1, 1)
        layout.addWidget(self._slot1_lbs[1], 1, 2)
        layout.addWidget(self._slot1_lbs[2], 1, 3)

        layout.addWidget(QtGui.QLabel(m.slot_2), 2, 0)
        self._slot2_lbs = (QtGui.QLabel(), QtGui.QPushButton(m.configure), QtGui.QPushButton(m.erase))
        self._slot2_lbs[1].clicked.connect(lambda: self.parent().configure(2))
        self._slot2_lbs[2].setVisible(False)
        self._slot2_lbs[2].clicked.connect(lambda: self.parent().erase(2))
        layout.addWidget(self._slot2_lbs[0], 2, 1)
        layout.addWidget(self._slot2_lbs[1], 2, 2)
        layout.addWidget(self._slot2_lbs[2], 2, 3)

        self._swap_slots = QtGui.QPushButton(m.swap)
        self._swap_slots.setVisible(False)
        self._swap_slots.clicked.connect(lambda: self.parent().swap())
        layout.addWidget(self._swap_slots, 3, 0)

        close = QtGui.QPushButton(m.close)
        close.setDefault(True)
        close.clicked.connect(self.parent().back)
        layout.addWidget(close, 4, 3, 1, 1)

        parent.slot_status.connect(self._slots_cb)

    def _slots_cb(self, slots):
        (stat1, stat2) = slots
        self._slot1_lbs[0].setText(m.configured if stat1 else m.blank)
        self._slot2_lbs[0].setText(m.configured if stat2 else m.blank)
        self._swap_slots.setVisible(stat1 or stat2)
        self._slot1_lbs[2].setVisible(stat1)
        self._slot2_lbs[2].setVisible(stat2)

class _WizardPage(QtGui.QWidget):
    title_text = m.slot_configuration
    description = None
    reject_text = m.previous
    accept_text = m.next_

    def __init__(self, slot, parent):
        super(_WizardPage, self).__init__(parent)

        self._slot = slot

        layout = QtGui.QFormLayout(self)
        layout.addRow(QtGui.QLabel('<h2>{}</h2>'.format(self.title_text)))

        if slot is not None and parent._slot_status[slot - 1]:
            layout.addRow(QtGui.QLabel('<b>' + m.warning + ':</b> ' + m.overwrite_existing))

        if self.description is not None:
            layout.addRow(QtGui.QLabel(self.description))

        self._build_ui(layout)

        buttons = QtGui.QDialogButtonBox()
        self._accept_btn = QtGui.QPushButton(self.accept_text)
        self._reject_btn = QtGui.QPushButton(self.reject_text)
        buttons.addButton(self._reject_btn, QtGui.QDialogButtonBox.RejectRole)
        buttons.addButton(self._accept_btn, QtGui.QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(parent.back)
        layout.addRow(buttons)

    @property
    def slot(self):
        return self._slot

    def setPrevEnabled(self, state):
        self._reject_btn.setEnabled(state)

    def setNextEnabled(self, state):
        self._accept_btn.setEnabled(state)

    def _build_ui(self, layout):
        pass

    def _accept(self):
        print('TODO: Next')

    def begin_work(self, message):
        page = _WritingConfig(self.title_text, message, self.parent())
        self.parent().push(page)
        return page


class _DeleteSlotPage(_WizardPage):
    description = m.deletes_content
    accept_text = m.delete

    def __init__(self, slot, parent):
        super(_DeleteSlotPage, self).__init__(slot, parent)

    @property
    def title_text(self):
        return m.erase_yubikey_slot.format(self.slot)

    def _accept(self):
        page = self.begin_work(m.erase_configuration)
        self.parent()._controller.delete_slot(self.slot, page.cb(m.configuration_erased))


class _SwapSlotsPage(_WizardPage):
    title_text = m.swap_slots
    description = m.swap_slots_desc
    accept_text = m.swap 

    def __init__(self, parent):
        super(_SwapSlotsPage, self).__init__(None, parent)

    def _accept(self):
        page = self.begin_work(m.writing_configuration)
        self.parent()._controller.swap_slots(page.cb(m.successfully_written))

class _ConfigureSlotType(_WizardPage):
    description = m.select_functionality

    def __init__(self, slot, parent):
        super(_ConfigureSlotType, self).__init__(slot, parent)
        self.setNextEnabled(False)

        # Do this after the window is drawn to avoid expanding the dialog.
        QtCore.QTimer.singleShot(0, lambda: self._action_desc.setText(m.supports_variety_of_protocols))

    def _build_ui(self, layout):
        self._action = QtGui.QButtonGroup(self)
        self._action_otp = QtGui.QRadioButton(m.yubikey_otp)
        self._action_cr = QtGui.QRadioButton(m.challenge_response)
        self._action_pw = QtGui.QRadioButton(m.static_password)
        self._action_hotp = QtGui.QRadioButton(m.oath_hotp)
        self._action.addButton(self._action_otp)
        self._action.addButton(self._action_cr)
        self._action.addButton(self._action_pw)
        self._action.addButton(self._action_hotp)
        self._action.buttonClicked.connect(self._select_action)

        grid = QtGui.QGridLayout()
        layout.addRow(grid)

        grid.addWidget(self._action_otp, 0, 0)
        grid.addWidget(self._action_cr, 1, 0)
        grid.addWidget(self._action_pw, 2, 0)
        grid.addWidget(self._action_hotp, 3, 0)

        self._action_desc = QtGui.QLabel()
        self._action_desc.setWordWrap(True)
        self._action_desc.setSizePolicy(QtGui.QSizePolicy.Expanding,
                                        QtGui.QSizePolicy.Minimum)
        grid.addWidget(self._action_desc, 0, 1, 4, 1)

    @property
    def title_text(self):
        return m.configure_yubikey_slot.format(self.slot)

    def _select_action(self, action):
        self.setNextEnabled(True)
        action = self._action.checkedButton()
        if action == self._action_otp:
            self._action_desc.setText(m.program_otp_desc)
        elif action == self._action_pw:
            self._action_desc.setText(m.program_static_password_desc)
        elif action == self._action_hotp:
            self._action_desc.setText(m.program_oath_hotp_desc)
        elif action == self._action_cr:
            self._action_desc.setText(m.program_challenge_resp_desc)

    def _accept(self):
        action = self._action.checkedButton()
        if action == self._action_otp:
            self.parent().push(_ConfigureOTP(self.slot, self.parent()))
        elif action == self._action_pw:
            self.parent().push(_ConfigureStaticPassword(self.slot, self.parent()))
        elif action == self._action_hotp:
            self.parent().push(_ConfigureHotp(self.slot, self.parent()))
        elif action == self._action_cr:
            self.parent().push(_ConfigureChalResp(self.slot, self.parent()))


class _ConfigureOTP(_WizardPage):
    description = m.otp_desc
    accept_text = m.write_configuration

    def __init__(self, slot, parent):
        super(_ConfigureOTP, self).__init__(slot, parent)
        self.setNextEnabled(False)

    @property
    def title_text(self):
        return m.configure_yubikey_otp_slot.format(self.slot)

    @property
    def key(self):
        return self._key_lbl.validator().fixup(self._key_lbl.text())

    @property
    def fixed(self):
        return self._fixed_lbl.validator().fixup(self._fixed_lbl.text())

    @property
    def uid(self):
        return self._uid_lbl.validator().fixup(self._uid_lbl.text())

    def _build_ui(self, layout):

        self._fixed_lbl = QtGui.QLineEdit()
        self._fixed_lbl.setValidator(ModhexValidator(0, 16))
        self._fixed_lbl.setMaximumWidth(100)
        self._fixed_lbl.textChanged.connect(self._on_change)
        self._fixed_cb = QtGui.QCheckBox(m.use_serial, None)
        self._fixed_cb.toggled.connect(self._use_serial)
        fixed_layout = QtGui.QHBoxLayout()
        fixed_layout.addWidget(self._fixed_lbl)
        fixed_layout.addWidget(self._fixed_cb)
        layout.addRow(m.public_id, fixed_layout)

        self._uid_lbl = QtGui.QLineEdit()
        self._uid_lbl.setValidator(HexValidator(6, 6))
        self._uid_lbl.setMaximumWidth(100)
        self._uid_lbl.textChanged.connect(self._on_change)
        self._uid_btn = QtGui.QPushButton(m.generate, None)
        self._uid_btn.clicked.connect(self._gen_uid)
        uid_layout = QtGui.QHBoxLayout()
        uid_layout.addWidget(self._uid_lbl)
        uid_layout.addWidget(self._uid_btn)
        layout.addRow(m.private_id, uid_layout)

        self._key_lbl = QtGui.QLineEdit()
        self._key_lbl.setValidator(HexValidator(16, 16))
        self._key_lbl.setMinimumWidth(240)
        self._key_lbl.textChanged.connect(self._on_change)
        self._key_btn = QtGui.QPushButton(m.generate, None)
        self._key_btn.clicked.connect(self._gen_key)
        key_layout = QtGui.QHBoxLayout()
        key_layout.addWidget(self._key_lbl)
        key_layout.addWidget(self._key_btn)
        layout.addRow(m.secret_key, key_layout)

        layout.setVerticalSpacing(2)

    def _on_change(self, changed):
        self.setNextEnabled(all(f.hasAcceptableInput() for f in [
            self._key_lbl,
            self._fixed_lbl,
            self._uid_lbl
        ]))

    def _accept(self):
        page = self.begin_work(m.writing_configuration)
        try:
            self.parent()._controller.program_otp(
                self.slot, self.key, self.fixed, self.uid,
                page.cb(m.successfully_written))
        except YkpersError as e:
            page.fail(e)

    def _gen_key(self):
        self._key_lbl.setText(b2a_hex(os.urandom(16)).decode('ascii'))

    def _gen_uid(self):
        self._uid_lbl.setText(b2a_hex(os.urandom(6)).decode('ascii'))

    def _use_serial(self, checked):
        if checked:
            serial = self.parent()._controller.serial
            serial = b'\xff\x00' + struct.pack(b'>I', serial)
            self._fixed_lbl.setText(modhex_encode(serial))
        self._fixed_lbl.setDisabled(checked)


class _ConfigureStaticPassword(_WizardPage):
    description = m.static_password_desc
    accept_text = m.write_configuration

    def __init__(self, slot, parent):
        super(_ConfigureStaticPassword, self).__init__(slot, parent)
        self.setNextEnabled(False)

    @property
    def title_text(self):
        return m.configure_static_password.format(self.slot)

    @property
    def static_pw(self):
        return self._static_pw_lbl.text()

    def _build_ui(self, layout):
        self._static_pw_lbl = QtGui.QLineEdit()
        self._static_pw_lbl.setPlaceholderText(m.password_32_char)
        self._static_pw_lbl.textChanged.connect(
            lambda t: self.setNextEnabled(bool(t)))
        layout.addRow(m.password, self._static_pw_lbl)
        layout_note = QtGui.QLabel(m.keyboard_layout_note)
        layout_note.setWordWrap(True)
        layout.addRow(layout_note)

    def _accept(self):
        page = self.begin_work(m.writing_configuration)
        self.parent()._controller.program_static(
            self.slot, self.static_pw,
            page.cb(m.successfully_written))


class _ConfigureHotp(_WizardPage):
    description = m.oath_hotp_desc
    accept_text = m.write_configuration

    def __init__(self, slot, parent):
        super(_ConfigureHotp, self).__init__(slot, parent)
        self.setNextEnabled(False)

    @property
    def title_text(self):
        return m.configure_hotp.format(self.slot)

    @property
    def key(self):
        return self._key_lbl.validator().fixup(self._key_lbl.text())

    @property
    def n_digits(self):
        return int(self._n_digits_box.currentText())

    def _build_ui(self, layout):
        self._key_lbl = QtGui.QLineEdit()
        self._key_lbl.setPlaceholderText(m.oath_secret)
        self._key_lbl.setValidator(B32Validator())
        self._key_lbl.textChanged.connect(
            lambda t: self.setNextEnabled(self._key_lbl.hasAcceptableInput()))
        layout.addRow(m.secret_key_base32, self._key_lbl)
        self._n_digits_box = QtGui.QComboBox()
        self._n_digits_box.addItems(['6', '8'])
        layout.addRow(m.number_of_digits, self._n_digits_box)

    def _accept(self):
        page = self.begin_work(m.writing_configuration)
        try:
            self.parent()._controller.program_hotp(
                self.slot, self.key, self.n_digits,
                page.cb(m.successfully_written))
        except YkpersError as e:
            page.fail(e)


class _ConfigureChalResp(_WizardPage):
    description = m.challenge_response_desc
    accept_text = m.write_configuration

    def __init__(self, slot, parent):
        super(_ConfigureChalResp, self).__init__(slot, parent)
        self.setNextEnabled(False)

    @property
    def title_text(self):
        return m.configure_challenge_resp.format(self.slot)

    @property
    def key(self):
        return self._key_lbl.validator().fixup(self._key_lbl.text())

    @property
    def touch(self):
        return self._touch_box.isChecked()

    def _build_ui(self, layout):
        self._key_lbl = QtGui.QLineEdit()
        self._key_lbl.setValidator(HexValidator(1, 20))
        self._key_lbl.setMinimumWidth(300)
        self._key_lbl.textChanged.connect(
            lambda t: self.setNextEnabled(self._key_lbl.hasAcceptableInput()))
        self._touch_box = QtGui.QCheckBox(m.require_touch)
        self._key_btn = QtGui.QPushButton(m.generate)
        self._key_btn.clicked.connect(self._gen_key)
        key_layout = QtGui.QHBoxLayout()
        key_layout.addWidget(self._key_lbl)
        key_layout.addWidget(self._key_btn)
        layout.addRow(m.secret_key, key_layout)
        layout.addRow(self._touch_box)

    def _accept(self):
        page = self.begin_work(m.writing_configuration)
        self.parent()._controller.program_chalresp(
            self.slot, self.key, self.touch,
            page.cb(m.successfully_written))

    def _gen_key(self):
        self._key_lbl.setText(b2a_hex(os.urandom(20)).decode('ascii'))

class _WritingConfig(_WizardPage):
    accept_text = m.finish

    def __init__(self, title, message, parent):
        self.title_text = title
        self._message = QtGui.QLabel(message)

        super(_WritingConfig, self).__init__(None, parent)
        self.setPrevEnabled(False)
        self.setNextEnabled(False)

    def _build_ui(self, layout):
        layout.addRow(self._message)

    def _accept(self):
        self.parent().reset()

    def complete(self, message):
        self._message.setText(message)
        self.setNextEnabled(True)

    def fail(self, error):
        self._message.setText(m.failed_to_write)
        self.setPrevEnabled(True)

    def cb(self, message):
        def _func(result):
            if isinstance(result, YkpersError):
                self.fail(result)
            else:
                self.complete(message)
        return _func


class SlotDialog(qt.Dialog):
    slot_status = QtCore.Signal(tuple)

    def __init__(self, controller, parent=None):
        super(SlotDialog, self).__init__(parent)

        self._controller = controller
        self._slot_status = (False, False)

        self.setWindowTitle(m.configure_yubikey_slots)

        QtGui.QStackedLayout(self)
        spacer = QtGui.QWidget()
        spacer.setFixedWidth(460)
        self.layout().addWidget(spacer)
        self.reset(True)

    def _slots_cb(self, res):
        self._slot_status = res
        self.slot_status.emit(res)

    def reset(self, initial=False):
        self._widget_stack = []
        if not initial:
            self.layout().removeWidget(self.layout().currentWidget())
        self.layout().insertWidget(0, _SlotStatus(self))
        self.layout().setCurrentIndex(0)
        self._controller.read_slots(self._slots_cb)

    def push(self, widget):
        current = self.layout().currentWidget()
        if current:
            self._widget_stack.append(current)
            self.layout().removeWidget(current)
        self.layout().insertWidget(0, widget)
        self.layout().setCurrentIndex(0)
        self.adjustSize()

    def back(self):
        if self._widget_stack:
            self.layout().removeWidget(self.layout().currentWidget())
            self.layout().insertWidget(0, self._widget_stack.pop())
            self.layout().setCurrentIndex(0)
            self.adjustSize()
        else:
            self.reject()

    def configure(self, slot):
        self.push(_ConfigureSlotType(slot, self))

    def erase(self, slot):
        self.push(_DeleteSlotPage(slot, self))

    def swap(self):
        self.push(_SwapSlotsPage(self))
