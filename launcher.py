"""Guided, local-only desktop entry point for Pieces Rescue."""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import webbrowser

import recovery
from recovery_io import Cancelled, exclusive
from release import VERSION


def pieces_running():
    if sys.platform != 'win32':
        return False
    result = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    if result.returncode:
        raise RuntimeError('Could not check running apps. Quit Pieces before continuing.')
    import csv
    return any(row and 'pieces' in row[0].lower() and 'rescue' not in row[0].lower()
               for row in csv.reader(result.stdout.splitlines()))


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('Pieces Rescue ' + VERSION)
    root.geometry('860x800')
    root.minsize(700, 560)
    root.configure(bg='#f6f5ef')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI', 11), background='#f6f5ef', foreground='#233b32')
    style.configure('TButton', padding=(12, 8))
    style.configure('Primary.TButton', background='#245b43', foreground='white')
    style.map('Primary.TButton', background=[('disabled', '#687c71'), ('active', '#19432f')])
    style.configure('Title.TLabel', font=('Georgia', 27, 'bold'))
    style.configure('Step.TLabel', font=('Segoe UI', 12, 'bold'))
    canvas = tk.Canvas(root, background='#f6f5ef', highlightthickness=0)
    scrollbar = ttk.Scrollbar(root, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    frame = ttk.Frame(canvas, padding=28)
    frame_id = canvas.create_window((0, 0), window=frame, anchor='nw')
    frame.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
    def resize(event):
        canvas.itemconfigure(frame_id, width=event.width)
        for widget in frame.winfo_children():
            if widget.winfo_class() == 'TLabel' and widget.cget('wraplength'):
                widget.configure(wraplength=max(300, event.width - 56))
    canvas.bind('<Configure>', resize)
    def wheel(event):
        if frame.winfo_height() > canvas.winfo_height():
            canvas.yview_scroll(-int(event.delta / 120), 'units')
    root.bind('<MouseWheel>', wheel)
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text='Keep your Pieces memories.', style='Title.TLabel').grid(row=0, sticky='w')
    ttk.Label(frame, text='Preserve a copy, recover the text, and explore it locally.\nNo Pieces account, upload, or ongoing service required.', wraplength=760).grid(row=1, sticky='w', pady=(8, 18))
    source = tk.StringVar()
    destination = tk.StringVar()
    closed = tk.BooleanVar()
    private = tk.BooleanVar()
    status = tk.StringVar(value='Choose your source and a new destination folder.')
    events = queue.Queue()
    cancel = threading.Event()
    state = {'busy': False, 'server': None, 'thread': None, 'lock': None, 'closing': False}

    ttk.Label(frame, text='1. Find your Pieces data', style='Step.TLabel').grid(row=2, sticky='w')
    row = ttk.Frame(frame); row.grid(row=3, sticky='ew', pady=(8, 4)); row.columnconfigure(0, weight=1)
    sources = ttk.Combobox(row, textvariable=source, width=60)
    sources.grid(row=0, column=0, sticky='ew', padx=(0, 8))
    def browse_source():
        name = filedialog.askopenfilename(title='Choose Pieces db.sqlite3 or a preserved snapshot', filetypes=[('SQLite database', '*.sqlite3 *.sqlite *.db'), ('All files', '*')])
        if name:
            source.set(name)
    ttk.Button(row, text='Browse...', command=browse_source).grid(row=0, column=1)
    def find():
        found = recovery.discover()
        sources['values'] = found
        if found:
            source.set(found[0])
            status.set('Found %d store(s). Check the full path; recover production and staging separately.' % len(found))
        else:
            status.set('No store found automatically. Browse to couchbase.cblite2/db.sqlite3 or a saved snapshot.')
    ttk.Button(frame, text='Find installed stores', command=find).grid(row=4, sticky='w', pady=(2, 14))
    ttk.Label(frame, text='2. Choose where to save the archive', style='Step.TLabel').grid(row=5, sticky='w')
    row = ttk.Frame(frame); row.grid(row=6, sticky='ew', pady=(8, 4)); row.columnconfigure(0, weight=1)
    ttk.Entry(row, textvariable=destination).grid(row=0, column=0, sticky='ew', padx=(0, 8))
    def browse_destination():
        name = filedialog.askdirectory(title='Choose a parent folder for a new Pieces archive')
        if name:
            from datetime import datetime
            destination.set(str(Path(name) / ('Pieces-archive-' + datetime.now().strftime('%Y%m%d-%H%M%S'))))
    ttk.Button(row, text='Browse...', command=browse_destination).grid(row=0, column=1)
    ttk.Label(frame, text='Use a private local drive with plenty of free space. The archive is not encrypted.\nCloud-synced or shared folders can expose captured text and credentials.', wraplength=760).grid(row=7, sticky='w', pady=(2, 12))
    ttk.Checkbutton(frame, text='I have quit Pieces OS and Pieces for Developers.', variable=closed).grid(row=8, sticky='w')
    ttk.Checkbutton(frame, text='I understand the saved source contains private memories and account data.', variable=private).grid(row=9, sticky='w', pady=(4, 16))
    ttk.Label(frame, text='3. Preserve, recover, and verify', style='Step.TLabel').grid(row=10, sticky='w')
    bar = ttk.Progressbar(frame, mode='indeterminate')
    bar.grid(row=11, sticky='ew', pady=(12, 8))
    ttk.Label(frame, textvariable=status, wraplength=780).grid(row=12, sticky='ew')
    controls = ttk.Frame(frame); controls.grid(row=13, sticky='ew', pady=(18, 12))
    action = ttk.Button(controls, text='Save my memories', style='Primary.TButton')
    action.pack(side='left')
    stop = ttk.Button(controls, text='Stop', state='disabled')
    stop.pack(side='left', padx=8)
    open_button = ttk.Button(controls, text='Open overview', state='disabled')
    open_button.pack(side='left')
    markdown_button = ttk.Button(controls, text='Export Markdown...', state='disabled')
    markdown_button.pack(side='left', padx=(8, 0))
    more = ttk.Frame(frame); more.grid(row=14, sticky='w')
    ttk.Label(frame, text='Public beta ' + VERSION + ' | Windows x64 | Keep your original Pieces folder.\nIf recovery stops, your saved files stay in the destination. Retry that folder to continue.', wraplength=760).grid(row=15, sticky='w', pady=(18, 0))

    def stop_server():
        if state['server']:
            state['server'].shutdown()
            state['server'].server_close()
            state['server'] = None
        if state['lock']:
            state['lock'].__exit__(None, None, None)
            state['lock'] = None

    def run(job):
        if state['busy']:
            return
        state['busy'] = True
        cancel.clear()
        action.configure(state='disabled'); stop.configure(state='normal'); open_button.configure(state='disabled')
        markdown_button.configure(state='disabled')
        bar.start(16)
        def worker():
            try:
                job()
            except (Cancelled, KeyboardInterrupt):
                events.put(('stopped', 'Stopped. Saved files were kept. Retry recovery in its destination; use a new folder for another Markdown export.'))
            except Exception as error:
                events.put(('error', str(error)))
            finally:
                events.put(('done', None))
        state['thread'] = threading.Thread(target=worker, daemon=False)
        state['thread'].start()

    def start():
        if not source.get().strip() or not destination.get().strip():
            messagebox.showinfo('Choose folders', 'Choose a Pieces database and a destination first.'); return
        if not closed.get() or not private.get():
            messagebox.showinfo('Before recovery', 'Quit both Pieces apps and review the private-data notice, then check both boxes.'); return
        selected_source, selected_destination = source.get(), destination.get()
        def work():
            stop_server()
            if pieces_running():
                raise RuntimeError('Pieces is still running. Quit it from the tray/menu and retry. Nothing has been overwritten.')
            recovery.recover(selected_source, selected_destination, True,
                             progress=lambda message: events.put(('progress', message)), cancel=cancel.is_set)
            events.put(('success', None))
        run(work)
    action.configure(command=start)
    def request_stop():
        cancel.set()
        status.set('Stopping at a safe point. Summary and viewer preparation may need to finish first.')
        stop.configure(state='disabled')
    stop.configure(command=request_stop)

    def open_view():
        selected = Path(destination.get()).expanduser().resolve()
        def work():
            stop_server()
            archive = selected / 'export' if (selected / 'recovery.json').exists() else selected
            if not (archive / 'knowledge.sqlite').is_file():
                raise FileNotFoundError('No recovered index found in this folder. Retry recovery first.')
            events.put(('progress', 'Opening the local overview...'))
            from viewer import make_server
            lock = exclusive(archive)
            lock.__enter__()
            try:
                server = make_server(archive, port=0)
            except BaseException:
                lock.__exit__(None, None, None)
                raise
            state['lock'] = lock
            state['server'] = server
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = 'http://127.0.0.1:%d/' % server.server_port
            webbrowser.open(url)
            events.put(('progress', 'Overview open at ' + url + ' Keep this launcher open while reading.'))
        run(work)
    open_button.configure(command=open_view)

    def export_notes():
        if state['busy']:
            return
        selected = Path(destination.get()).expanduser().resolve()
        parent = filedialog.askdirectory(title='Choose a private parent folder for new Markdown notes')
        if not parent:
            return
        from datetime import datetime
        output = Path(parent) / ('Pieces-notes-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        def work():
            stop_server()
            from portable import export_markdown
            export_markdown(selected, output,
                            progress=lambda message: events.put(('progress', message)), cancel=cancel.is_set)
            events.put(('markdown', str(output)))
        run(work)
    markdown_button.configure(command=export_notes)

    def existing():
        if state['busy']:
            return
        name = filedialog.askdirectory(title='Choose the saved archive folder (containing recovery.json)')
        if not name:
            return
        destination.set(name)
        try:
            receipt = json.loads((Path(name) / 'recovery.json').read_text(encoding='utf-8'))
            source.set(receipt.get('source_identity', {}).get('path', ''))
            status.set('Saved recovery: ' + receipt.get('status', 'unknown') + '. Use Save my memories to retry, or open the recovered overview.')
        except (OSError, ValueError):
            status.set('Selected an existing export. Open overview to read it.')
        available = (Path(name) / 'knowledge.sqlite').is_file() or (Path(name) / 'export/knowledge.sqlite').is_file()
        open_button.configure(state='normal' if available else 'disabled')
        markdown_button.configure(state='normal' if available else 'disabled')
    ttk.Button(more, text='Open / retry saved archive...', command=existing).pack(side='left')
    def diagnostic():
        if state['busy'] or not destination.get():
            return
        try:
            text = json.dumps(recovery.diagnostics(destination.get()), indent=2)
            messagebox.showinfo('Safe diagnostics', text + '\n\nOnly counts, platform and status are shown. No memories, paths or account identifiers.')
            root.clipboard_clear(); root.clipboard_append(text)
            status.set('Safe diagnostics copied to the clipboard. Nothing was sent.')
        except (OSError, ValueError):
            messagebox.showinfo('No receipt yet', 'Choose a saved recovery folder first.')
    ttk.Button(more, text='Copy safe diagnostics', command=diagnostic).pack(side='left', padx=8)

    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == 'progress' or kind == 'stopped':
                    status.set(value)
                elif kind == 'error':
                    status.set('This operation needs attention. Your saved files were kept.')
                    messagebox.showerror('Operation needs attention', value + '\n\nKeep the saved archive and any unfinished output. Retry recovery in its destination; use a new folder for another Markdown export.')
                elif kind == 'success':
                    status.set('Saved and verified. Open overview to explore your memories. Keep the preserved folder as your backup.')
                elif kind == 'markdown':
                    status.set('Markdown saved. Open index.md in your editor, or open the notes folder as an Obsidian vault.')
                    messagebox.showinfo('Markdown saved', 'Your notes are in:\n' + value + '\n\nStart with index.md. Keep this folder together so its links work. These notes contain private source text; they are not a replacement for your preserved archive.')
                elif kind == 'done':
                    state['busy'] = False
                    bar.stop(); action.configure(state='normal'); stop.configure(state='disabled')
                    path = Path(destination.get())
                    if (path / 'export/knowledge.sqlite').is_file() or (path / 'knowledge.sqlite').is_file():
                        open_button.configure(state='normal')
                        markdown_button.configure(state='normal')
                    if state['closing']:
                        stop_server(); root.destroy(); return
        except queue.Empty:
            pass
        root.after(100, poll)
    def close():
        if state['busy']:
            if messagebox.askyesno('Stop recovery?', 'Stop at a safe point and close? Saved checkpoints will be kept.'):
                state['closing'] = True
                request_stop()
        else:
            stop_server(); root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.after(100, poll)
    root.after(200, find)
    root.mainloop()


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == '--cli':
            sys.argv.pop(1)
            return recovery.main()
        if sys.argv[1] == '--serve' and len(sys.argv) >= 3:
            from viewer import serve
            serve(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 8765)
            return 0
        raise SystemExit('Use no arguments for the launcher, --cli for recovery commands, or --serve EXPORT [PORT].')
    gui()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
