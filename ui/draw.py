import tkinter as tk

class DrawWindow:
    def __init__(self, parent_root):
        self.root = parent_root
        
        self.win = tk.Toplevel(self.root)
        self.win.title("Test Sheet")
        
        try:
            self.win.state("zoomed")
        except tk.TclError:
            self.win.attributes("-zoomed", True)
            
        self.w = self.win.winfo_screenwidth()
        self.h = self.win.winfo_screenheight()
        
        self.sheet = tk.Canvas(self.win, width=self.w, height=self.h, bg="white", highlightthickness=0)
        self.sheet.pack(fill=tk.BOTH, expand=True)
        
        self.sheet.create_text(40, 50, text="Hello", font=("Arial", 14, "bold"), fill="#960000", anchor="w")
        
    def move_mouse(self, x, y):
        if not self.win.winfo_exists(): return
        self.sheet.delete("all")
  
        self.sheet.create_oval(x-20, y-20, x+20, y+20, fill="red", outline="")