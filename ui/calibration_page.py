import tkinter as tk

class CalibrationWindow:
    def __init__(self, parent_root, engine):
        self.root = parent_root
        self.engine = engine
        self.features = None 
        
        self.win = tk.Toplevel(self.root)
        self.win.title("Calibration Target Sheet")
        
        try: self.win.state("zoomed")
        except tk.TclError: self.win.attributes("-zoomed", True)
            
        self.w = self.win.winfo_screenwidth()
        self.h = self.win.winfo_screenheight()
        
        self.sheet = tk.Canvas(self.win, width=self.w, height=self.h, bg="white", highlightthickness=0)
        self.sheet.pack(fill=tk.BOTH, expand=True)
        
        self.targets = [
            (100, 100), 
            (self.w-100, 100), 
            (100, self.h-100), 
            (self.w-100, self.h-100), 
            (self.w//2, self.h//2)
        ]
        self.target_idx = 0
        
        self.is_tuning = False
        self.current_progress = 0
        
        self.win.focus_force()

    def render_tick(self):
        if not self.win.winfo_exists(): return
        self.sheet.delete("all")
        
        # --- DRAW LOADER BAR IF NETWORK IS CURRENTLY OPTIMIZING ---
        if self.is_tuning:
            cx = self.w // 2
            cy = self.h // 2
            
            bar_width = 400
            bar_height = 30
            
            # Dimensions coordinates
            bx1 = cx - (bar_width // 2)
            by1 = cy - (bar_height // 2)
            bx2 = cx + (bar_width // 2)
            by2 = cy + (bar_height // 2)
            
            # Title tracking message
            self.sheet.create_text(cx, cy - 60, text="Optimizing Gaze Models on Local Features...", font=("Arial", 16, "bold"), fill="#1e293b")
            self.sheet.create_text(cx, cy - 30, text="Please keep your head completely static and wait", font=("Arial", 11, "italic"), fill="#64748b")
            
            # Background Bar Track container block
            self.sheet.create_rectangle(bx1, by1, bx2, by2, outline="#334155", width=2, fill="#f1f5f9")
            
            # Dynamically compute the progress filling dimensions
            prog = self.current_progress
            if prog > 0:
                fill_end_x = bx1 + int((prog / 100) * bar_width)
                self.sheet.create_rectangle(bx1 + 2, by1 + 2, fill_end_x - 2, by2 - 2, fill="#06b6d4", outline="")
                
            # Text metric percentages
            self.sheet.create_text(cx, cy + 40, text=f"{prog}% Optimized", font=("Arial", 12, "bold"), fill="#0f172a")
            return
            
        # --- STANDARD RENDERING OPERATION (Capturing Targets) ---
        tx, ty = self.targets[self.target_idx]
        self.sheet.create_oval(tx-15, ty-15, tx+15, ty+15, fill="black", outline="")
        
        captured = len(self.engine.calibration_samples)
        stats = f"Samples Logged: {captured} / 5  [Press SPACE to Capture | T to Fine-Tune Model | Q to Close]"
        self.sheet.create_text(40, 50, text=stats, font=("Arial", 14, "bold"), fill="#960000", anchor="w")