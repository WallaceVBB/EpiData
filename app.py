# Fichier qui va controler le cycle de vie de l'application

### Bibliothèques
import tkinter as tk
from tkinter import ttk
import threading
from services import data_service
#import pages

### Fonctions

class SplashScreen(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Ouvrant votre Cantine Numérique...)")
        self.geometry("400x200")
        
        #Status Label (AF: afficher l'étape chargement en cours)
        self.label_status = ttk.Label(self, text="Chargement en cours...", font=("Arial", 16))
        self.label_status.pack(expand=True)

        # AF: Ajouter une image et la version de l'application


class Application(tk.Tk):
    def __init__(self):
        super().__init__()

        # Fermer la fenêtre principale pendant le splash screen
        self.withdraw()

        # Ouvrir le splash screen
        self.splash = SplashScreen(self)

        self.data_service = data_service(self)
        
        # Charger les données en arrière-plan (Splash Screen)
        thread = threading.Thread(target=self._start_loading)
        thread.start()


    def _start_loading(self):
        def update_status(message):
            self.after(0, lambda:self.splash.label_status.config(text=message))

        # Simuler le chargement des données
        self.data_service.initialiser_dataset(self.splash.label_status)

        # Une fois le chargement terminé, afficher la fenêtre principale
        self.after(0, self._show_main_app)
    
    def _show_main_app(self):
        
        self.splash.destroy() # Fermer le splash screen

        # Configurer la fenêtre principale
        self.title("Cantine Numérique")
        self.geometry("800x600")
        self.deiconify()  # Afficher la fenêtre principale

        # Création du container des pages
        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)

        self.show_frame("PageAccueil")
        
    def show_frame(self, page_name):

        if page_name not in self.frames:
            page_class = getattr(pages, page_name)
            frame = page_class(parent=self.container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        frame = self.frames[page_name]
        frame.tkraise()

        if hasattr(frame, "on_show"):
            frame.on_show()
