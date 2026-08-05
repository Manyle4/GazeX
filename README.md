# GazeX: An assistive gaze estimation desktop platform

## Project Structure
```text
Eyetheia-Gaze-Tracking-System/
│
├── core/                   # Neural network layers and training definitions
│   ├── dataset.py
│   ├── engine.py
│   └── model.py
│
├── ui/                     # Graphical User Interface windows and style layouts
│   ├── calibration_page.py
│   ├── draw.py
│   ├── main_dashboard.py
│   ├── styles.py
│   ├── test.py
│   └── vlc.py
│
├── utils/                  # Coordinate filters, landmarks, and snapping handlers
│   ├── filters.py
│   ├── landmarks.py
│   └── snapping.py
│
├── app.py                  # Core application entry point
├── README.md               # System setup instructions blueprint
└── requirements.txt        # Requirements and libraries file              
```

## AI models  
Download the models from the google drive folder [this link](https://drive.google.com/drive/folders/1HctHugiloZXlQdLVYwzirQUiun6tvBSk?usp=drive_link)

## Installation
1. Clone the repository
```
git clone https://github.com/Manyle4/GazeX
cd GazeX
```
2. Create and run the virtual environment
```
python -m venv env
env\Scripts\activate
```
3. Run the command below to intsall the needed libraries
```
pip install -r requirements.txt
```
4. Create a models folder in the root directory of the app and place the model files in the models folder
5. Run the command below to startup the desktop app
```
python app.py
```