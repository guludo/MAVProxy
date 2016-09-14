# Copyright (C) 2016  Intel Corporation. All rights reserved.
#
# This file is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This file is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
GUI for calibrating compass. This is adapted from Ardupilot's local MAVProxy
module magcal_graph. Some people read it "magical_graph" at the time of
release, thus the silly reason for the name of this module.
"""
from pymavlink import mavutil
import multiprocessing

from MAVProxy.modules.lib import mp_module, mp_util

class MagicalModule(mp_module.MPModule):
    def __init__(self, mpstate):
        super(MagicalModule, self).__init__(mpstate, 'magical')
        self.add_command(
            'magical',
            self.cmd_magical,
            'open the GUI for compass calibration',
        )

        self.mpstate = mpstate
        self.parent_pipe, self.child_pipe = multiprocessing.Pipe()
        self.ui_process = None
        self.progress_msgs = {}
        self.report_msgs = {}
        self.attitude_msg = None
        self.raw_imu_msg = None
        self.running = False
        self.last_ui_msgs = {}

    def start_ui(self):
        if self.ui_is_active():
            return
        if self.ui_process:
            self.ui_process.join()

        self.ui_process = multiprocessing.Process(target=self.ui_task)
        self.update_ui()
        self.ui_process.start()

    def stop_ui(self):
        if not self.ui_is_active():
            return

        self.parent_pipe.send(dict(name='close'))
        self.ui_process.join()

    def ui_task(self):
        mp_util.child_close_fds()

        from MAVProxy.modules.lib import wx_processguard
        from MAVProxy.modules.lib.wx_loader import wx
        from MAVProxy.modules.mavproxy_magical.magical_ui import MagicalFrame

        app = wx.App(False)
        app.frame = MagicalFrame(self.child_pipe)
        app.frame.Show()
        app.MainLoop()

    def process_ui_commands(self):
        while self.parent_pipe.poll():
            cmd = self.parent_pipe.recv()

            if cmd == 'start':
                self.mpstate.functions.process_stdin('magcal start')
            elif cmd == 'cancel':
                self.mpstate.functions.process_stdin('magcal cancel')

    def ui_is_active(self):
        return self.ui_process is not None and self.ui_process.is_alive()

    def idle_task(self):
        self.process_ui_commands()
        if self.ui_is_active():
            self.update_ui()
        elif self.last_ui_msgs:
            self.last_ui_msgs = {}

    def cmd_magical(self, args):
        self.start_ui()

    def mavlink_packet(self, m):
        if m.get_type() == 'MAG_CAL_PROGRESS':
            self.progress_msgs[m.compass_id] = m
            if m.compass_id in self.report_msgs:
                del self.report_msgs[m.compass_id]
            if 'report' in self.last_ui_msgs:
                del self.last_ui_msgs['report']
            self.running = True
        elif m.get_type() == 'MAG_CAL_REPORT':
            self.report_msgs[m.compass_id] = m
            if self.report_msgs and len(self.report_msgs) == len(self.progress_msgs):
                self.running = False
        elif m.get_type() == 'ATTITUDE':
            self.attitude_msg = m
        elif m.get_type() == 'RAW_IMU':
            self.raw_imu_msg = m
        elif m.get_type() == 'COMMAND_ACK':
            if m.command == mavutil.mavlink.MAV_CMD_DO_CANCEL_MAG_CAL:
                self.running = False

    def unload(self):
        self.stop_ui()

    def send_ui_msg(self, m):
        send = False
        if m['name'] not in self.last_ui_msgs:
            send = True
        else:
            last = self.last_ui_msgs[m['name']]
            if m['name'] == 'report':
                if len(m['messages']) != len(last['messages']):
                    send = True
                else:
                    for a, b in zip(m['messages'], last['messages']):
                        if a.compass_id != b.compass_id:
                            send = True
                            break
            else:
                send = m != last

        if not send:
            return

        self.parent_pipe.send(m)
        self.last_ui_msgs[m['name']] = m

    def update_ui(self):
        self.send_ui_msg(dict(
            name='ui_is_active',
            value=self.ui_is_active(),
        ))

        if self.progress_msgs:
            pct = min(p.completion_pct for p in self.progress_msgs.values())
            masks = [~0] * 10
            for p in self.progress_msgs.values():
                for i in range(10):
                    masks[i] &= p.completion_mask[i]
            visible = [bool(m & 1 << j) for m in masks for j in range(8)]

            self.send_ui_msg(dict(
                name='progress_update',
                pct=pct,
                sections=visible,
            ))

        if self.report_msgs and len(self.report_msgs) == len(self.progress_msgs):
            keys = sorted(self.progress_msgs.keys())
            self.send_ui_msg(dict(
                name='report',
                messages=[self.report_msgs[k] for k in keys],
            ))

        if self.attitude_msg:
            self.send_ui_msg(dict(
                name='attitude',
                roll=self.attitude_msg.roll,
                pitch=self.attitude_msg.pitch,
                yaw=self.attitude_msg.yaw,
                gx=self.attitude_msg.rollspeed,
                gy=self.attitude_msg.pitchspeed,
                gz=self.attitude_msg.yawspeed,
                timestamp=self.attitude_msg.time_boot_ms,
            ))

        if self.raw_imu_msg:
            self.send_ui_msg(dict(
                name='mag',
                x=self.raw_imu_msg.xmag,
                y=self.raw_imu_msg.ymag,
                z=self.raw_imu_msg.zmag,
            ))


        self.send_ui_msg(dict(
            name='running',
            value=self.running,
        ))

def init(mpstate):
    return MagicalModule(mpstate)
