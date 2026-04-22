import os
import sys
import json
import threading
import queue
import time
import subprocess
import urllib.request
import zipfile
import numpy as np
from scipy.signal import butter, sosfilt
import sounddevice as sd
import customtkinter as ctk
import tkinter.messagebox as messagebox

CONFIG_FILE = "ssup_woofer_config.json"
NIRCMD_URL = "https://www.nirsoft.net/utils/nircmd-x64.zip"
VBCABLE_URL = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def get_nircmd():
    if not os.path.exists("nircmd.exe"):
        try:
            urllib.request.urlretrieve(NIRCMD_URL, "nircmd.zip")
            with zipfile.ZipFile("nircmd.zip", 'r') as z:
                z.extract("nircmd.exe")
                z.extract("nircmdc.exe")
            os.remove("nircmd.zip")
        except:
            pass

def check_cable():
    try:
        for d in sd.query_devices():
            if "CABLE Input" in d['name'] or "VB-Audio" in d['name']:
                return True
    except:
        pass
    return False

def install_cable():
    z_path = "vbcable_pack.zip"
    folder = "vbcable_setup"
    if not os.path.exists(folder):
        urllib.request.urlretrieve(VBCABLE_URL, z_path)
        with zipfile.ZipFile(z_path, 'r') as z:
            z.extractall(folder)
        os.remove(z_path)
    exe_path = os.path.join(folder, "VBCABLE_Setup_x64.exe")
    os.startfile(exe_path)

def set_audio_device(dev_name):
    get_nircmd()
    if os.path.exists("nircmdc.exe"):
        subprocess.run(["nircmdc.exe", "setdefaultsounddevice", dev_name])

def list_devices():
    try:
        devs = sd.query_devices()
        ins = []
        outs = []
        for i, d in enumerate(devs):
            name = f"[{i}] {d['name']}"
            if d['max_input_channels'] > 0:
                ins.append(name)
            if d['max_output_channels'] > 0:
                outs.append(name)
        return ins, outs
    except:
        return [], []

class Processor(threading.Thread):
    def __init__(self, c_in, c_main, c_sub, cross=120, d_ms=150, s_gain=1.0, m_gain=1.0, mode='crossover'):
        super().__init__()
        self.c_in = c_in
        self.c_main = c_main
        self.c_sub = c_sub
        self.cross = cross
        self.d_ms = d_ms
        self.s_gain = s_gain
        self.m_gain = m_gain
        self.mode = mode
        self.s_rate = 48000
        
        for r in [48000, 44100, 96000, 32000, 24000, 16000, 8000]:
            try:
                sd.check_input_settings(device=self.c_in, channels=2, samplerate=r)
                sd.check_output_settings(device=self.c_main, channels=2, samplerate=r)
                sd.check_output_settings(device=self.c_sub, channels=2, samplerate=r)
                self.s_rate = r
                break
            except:
                pass
                
        self.b_size = 1024
        self.q_main = queue.Queue()
        self.q_sub = queue.Queue()
        self.active = False
        self.streams = []
        self.update_filters()

    def update_filters(self):
        nyq = 0.5 * self.s_rate
        cutoff = self.cross / nyq
        if cutoff >= 1.0 or cutoff <= 0.0:
            cutoff = 120 / nyq
        self.hp = butter(4, cutoff, btype='high', output='sos')
        self.lp = butter(4, cutoff, btype='low', output='sos')
        self.zi_hp = np.zeros((self.hp.shape[0], 2, 2), dtype=np.float64)
        self.zi_lp = np.zeros((self.lp.shape[0], 2, 2), dtype=np.float64)

    def set_params(self, c, d, sg, mg, m):
        self.s_gain = sg
        self.m_gain = mg
        self.mode = m
        if self.cross != c:
            self.cross = c
            self.update_filters()
        if self.d_ms != d:
            self.d_ms = d
            while not self.q_main.empty():
                try: self.q_main.get_nowait()
                except queue.Empty: break
            self.fill_delay()

    def fill_delay(self):
        samps = int((self.d_ms / 1000.0) * self.s_rate)
        blks = samps // self.b_size
        for _ in range(blks):
            self.q_main.put(np.zeros((self.b_size, 2), dtype=np.float32))

    def trigger_pulse(self):
        p = np.zeros((self.b_size, 2), dtype=np.float32)
        p[0:10, :] = 1.0
        self.q_main.put(p)
        self.q_sub.put(p)

    def process_in(self, data, frames, time, status):
        aud = data.copy()
        if aud.shape[1] == 1:
            aud = np.column_stack((aud, aud))

        aud64 = aud.astype(np.float64)
        if self.mode == 'clone':
            out_m = aud64.copy()
            out_s = aud64.copy()
        else:
            out_m, self.zi_hp = sosfilt(self.hp, aud64, axis=0, zi=self.zi_hp)
            out_s, self.zi_lp = sosfilt(self.lp, aud64, axis=0, zi=self.zi_lp)

        out_s = out_s * self.s_gain
        out_m = out_m * self.m_gain
        out_s = np.tanh(out_s)
        out_m = np.clip(out_m, -1.0, 1.0)

        self.q_main.put(out_m.astype(np.float32))
        self.q_sub.put(out_s.astype(np.float32))

    def process_main(self, data, frames, time, status):
        try:
            data[:] = self.q_main.get_nowait()
        except queue.Empty:
            data.fill(0)

    def process_sub(self, data, frames, time, status):
        try:
            data[:] = self.q_sub.get_nowait()
        except queue.Empty:
            data.fill(0)

    def run(self):
        self.active = True
        self.fill_delay()
        try:
            self.streams = [
                sd.InputStream(device=self.c_in, channels=2, samplerate=self.s_rate, blocksize=self.b_size, callback=self.process_in),
                sd.OutputStream(device=self.c_main, channels=2, samplerate=self.s_rate, blocksize=self.b_size, callback=self.process_main),
                sd.OutputStream(device=self.c_sub, channels=2, samplerate=self.s_rate, blocksize=self.b_size, callback=self.process_sub)
            ]
            for s in self.streams:
                s.start()
            while self.active:
                time.sleep(0.1)
        except:
            pass
        finally:
            self.stop()

    def stop(self):
        self.active = False
        for s in self.streams:
            try:
                s.stop()
                s.close()
            except:
                pass
        self.streams = []

class SsupWoofer(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SsupWoofer")
        self.geometry("600x800")
        self.protocol("WM_DELETE_WINDOW", self.cleanup)
        self.proc = None
        self.old_dev = None
        self.opts = {
            "in": "", "main": "", "sub": "",
            "cross": 120, "delay": 150, "hijack": True,
            "s_gain": 1.0, "m_gain": 1.0, "mode": "2.1 Crossover"
        }
        self.load_prefs()
        self.setup_ui()
        self.apply_prefs()

    def setup_ui(self):
        ins, outs = list_devices()
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sf = ctk.CTkScrollableFrame(self)
        self.sf.grid(row=0, column=0, sticky="nsew")
        self.sf.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(self.sf, text="SsupWoofer", font=("Inter", 24, "bold")).grid(row=0, column=0, pady=(20, 10))
        
        f1 = ctk.CTkFrame(self.sf)
        f1.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        ctk.CTkLabel(f1, text="1. Audio Routing", font=("Inter", 16, "bold")).pack(anchor="w", padx=10, pady=(10,5))
        
        ctk.CTkLabel(f1, text="Capture Device:").pack(anchor="w", padx=10)
        self.cb_in = ctk.CTkComboBox(f1, values=ins, width=500)
        self.cb_in.pack(padx=10, pady=(0, 10))
        
        ctk.CTkLabel(f1, text="Main Speakers:").pack(anchor="w", padx=10)
        self.cb_main = ctk.CTkComboBox(f1, values=outs, width=500)
        self.cb_main.pack(padx=10, pady=(0, 10))

        ctk.CTkLabel(f1, text="Subwoofer:").pack(anchor="w", padx=10)
        self.cb_sub = ctk.CTkComboBox(f1, values=outs, width=500)
        self.cb_sub.pack(padx=10, pady=(0, 10))
        
        self.chk_hijack = ctk.CTkCheckBox(f1, text="Auto-Hijack System Audio")
        self.chk_hijack.pack(padx=10, pady=(5, 15), anchor="w")

        f2 = ctk.CTkFrame(self.sf)
        f2.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        ctk.CTkLabel(f2, text="2. Crossover & Tuning", font=("Inter", 16, "bold")).pack(anchor="w", padx=10, pady=(10,5))
        
        self.lbl_m = ctk.CTkLabel(f2, text="Mode:")
        self.lbl_m.pack(anchor="w", padx=10)
        self.cb_mode = ctk.CTkComboBox(f2, values=["2.1 Crossover", "Full Range"], command=self.on_slide)
        self.cb_mode.pack(fill="x", padx=10, pady=(0,10))
        
        self.lbl_sg = ctk.CTkLabel(f2, text="Sub Gain: 1.0x")
        self.lbl_sg.pack(anchor="w", padx=10)
        self.sl_sg = ctk.CTkSlider(f2, from_=0.0, to=5.0, number_of_steps=50, command=self.on_slide)
        self.sl_sg.pack(fill="x", padx=10, pady=(0,10))

        self.lbl_mg = ctk.CTkLabel(f2, text="Main Gain: 1.0x")
        self.lbl_mg.pack(anchor="w", padx=10)
        self.sl_mg = ctk.CTkSlider(f2, from_=0.0, to=2.0, number_of_steps=40, command=self.on_slide)
        self.sl_mg.pack(fill="x", padx=10, pady=(0,10))

        self.lbl_c = ctk.CTkLabel(f2, text="Crossover: 120 Hz")
        self.lbl_c.pack(anchor="w", padx=10)
        self.sl_c = ctk.CTkSlider(f2, from_=40, to=500, command=self.on_slide)
        self.sl_c.pack(fill="x", padx=10, pady=(0,10))

        self.lbl_d = ctk.CTkLabel(f2, text="Delay: 150 ms")
        self.lbl_d.pack(anchor="w", padx=10)
        self.sl_d = ctk.CTkSlider(f2, from_=0, to=5000, command=self.on_slide)
        self.sl_d.pack(fill="x", padx=10, pady=(0,10))

        f3 = ctk.CTkFrame(self.sf)
        f3.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        ctk.CTkLabel(f3, text="3. Tools", font=("Inter", 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=5)
        
        self.btn_p = ctk.CTkButton(f3, text="Sync Pulse", command=self.pulse)
        self.btn_p.grid(row=1, column=0, padx=10, pady=10)
        
        self.btn_r = ctk.CTkButton(f3, text="Restore Default Audio", fg_color="#C8504B", hover_color="#8c3834", command=self.restore_click)
        self.btn_r.grid(row=1, column=1, padx=10, pady=10)

        self.btn_i = ctk.CTkButton(self.sf, text="Install VB-Cable", height=50, fg_color="#C8504B", hover_color="#8c3834", command=self.do_install)
        if not check_cable():
            self.btn_i.grid(row=4, column=0, padx=20, pady=(20, 0), sticky="ew")

        self.btn_s = ctk.CTkButton(self.sf, text="START", height=50, font=("Inter", 18, "bold"), command=self.toggle)
        self.btn_s.grid(row=5, column=0, padx=20, pady=20, sticky="ew")

    def do_install(self):
        try:
            install_cable()
        except:
            pass

    def on_slide(self, val=None):
        c = int(self.sl_c.get())
        d = int(self.sl_d.get())
        sg = round(self.sl_sg.get(), 1)
        mg = round(self.sl_mg.get(), 1)
        m_val = self.cb_mode.get()
        m = 'clone' if 'Full' in m_val else 'crossover'
        
        self.lbl_c.configure(text=f"Crossover: {c} Hz")
        self.lbl_d.configure(text=f"Delay: {d} ms")
        self.lbl_sg.configure(text=f"Sub Gain: {sg}x")
        self.lbl_mg.configure(text=f"Main Gain: {mg}x")
        
        if self.proc and self.proc.active:
            self.proc.set_params(c, d, sg, mg, m)

    def pulse(self):
        if self.proc and self.proc.active:
            self.proc.trigger_pulse()

    def get_id(self, s):
        if not s: return None
        try:
            return int(s.split("]")[0].replace("[", ""))
        except:
            return None

    def toggle(self):
        if self.proc and self.proc.active:
            self.proc.stop()
            self.btn_s.configure(text="START", fg_color=["#3a7ebf", "#1f538d"])
            self.revert_audio()
        else:
            i = self.get_id(self.cb_in.get())
            m = self.get_id(self.cb_main.get())
            s = self.get_id(self.cb_sub.get())
            if i is None or m is None or s is None:
                return

            c = int(self.sl_c.get())
            d = int(self.sl_d.get())
            sg = round(self.sl_sg.get(), 1)
            mg = round(self.sl_mg.get(), 1)
            mv = self.cb_mode.get()
            md = 'clone' if 'Full' in mv else 'crossover'
            
            self.proc = Processor(i, m, s, c, d, sg, mg, md)
            self.proc.start()
            self.btn_s.configure(text="STOP", fg_color="#C8504B", hover_color="#8c3834")
            if self.chk_hijack.get():
                self.hijack()
            self.save_prefs()

    def hijack(self):
        try:
            d_idx = sd.default.device[1]
            info = sd.query_devices(d_idx)
            self.old_dev = info['name'].split("(")[0].strip()
            set_audio_device("CABLE Input")
        except:
            pass

    def revert_audio(self):
        if self.chk_hijack.get() and self.old_dev:
            set_audio_device(self.old_dev)

    def restore_click(self):
        v = self.cb_main.get()
        if v:
            p = v.split("] ")[1].split("(")[0].strip()
            set_audio_device(p)

    def load_prefs(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    self.opts.update(json.load(f))
            except:
                pass

    def apply_prefs(self):
        ins, outs = list_devices()
        for x in ins:
            if self.opts["in"] in x: self.cb_in.set(x)
        for x in outs:
            if self.opts["main"] in x: self.cb_main.set(x)
            if self.opts["sub"] in x: self.cb_sub.set(x)
            
        self.sl_c.set(self.opts.get("cross", 120))
        self.sl_d.set(self.opts.get("delay", 150))
        self.sl_sg.set(self.opts.get("s_gain", 1.0))
        self.sl_mg.set(self.opts.get("m_gain", 1.0))
        self.cb_mode.set(self.opts.get("mode", "2.1 Crossover"))
        
        if self.opts["hijack"]:
            self.chk_hijack.select()
        else:
            self.chk_hijack.deselect()
        self.on_slide()

    def save_prefs(self):
        self.opts["in"] = self.cb_in.get()
        self.opts["main"] = self.cb_main.get()
        self.opts["sub"] = self.cb_sub.get()
        self.opts["cross"] = int(self.sl_c.get())
        self.opts["delay"] = int(self.sl_d.get())
        self.opts["s_gain"] = round(self.sl_sg.get(), 1)
        self.opts["m_gain"] = round(self.sl_mg.get(), 1)
        self.opts["mode"] = self.cb_mode.get()
        self.opts["hijack"] = bool(self.chk_hijack.get())
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.opts, f)
        except:
            pass

    def cleanup(self):
        if self.proc and self.proc.active:
            self.proc.stop()
        self.revert_audio()
        self.save_prefs()
        self.destroy()

if __name__ == "__main__":
    app = SsupWoofer()
    app.mainloop()
