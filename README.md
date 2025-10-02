# spotDL Web Downloader

<p align="center">
   <img src="public/spotdl_cask_new.gif?v=1" alt="spotDL Web Downloader demo" width="640" />
</p>

## Project Summary

spotDL Web Downloader transforms the command-line [spotdl](https://github.com/spotDL/spotify-downloader) experience into a user-friendly web application. Simply paste Spotify or YouTube links, configure your download preferences, and let the app handle the rest with real-time progress updates and batch processing capabilities.

## Key Features

- **Drag & Drop Support** - Drop links directly onto the interface
- **Paste Detection** - Automatically detects links from clipboard (Ctrl+V / ⌘V)
- **Batch Processing** - Add multiple tracks and download them all at once
- **Audio Quality Control** - Choose from 128k to 320k bitrates or original quality
- **Multiple Formats** - MP3, FLAC, M4A, OPUS, OGG, WAV support
- **Custom Naming** - Flexible filename templates (Artist-Title, Title-Artist, etc.)

## Tech Stack

### **Backend**
- **Flask**
- **pywebview**
- **spotDL** (`spotdl>=4.0.0`)
- **RESTful API**
- **Server-Sent Events (SSE)**

### **Frontend**
- **JavaScript**
- **HTML5**
- **CSS3**
- **SVG**

## Usage

### **Getting Started**

1. **Clone the repository**
   (Repository slug remains `spotdl-cask`; the product name is now **spotDL Web Downloader**.)
   ```bash
   git clone https://github.com/yourusername/spotdl-cask.git
   cd spotdl-cask
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**
   ```bash
   python app.py
   ```
   
   For development mode with debug enabled:
   ```bash
   python app.py --dev
   ```

4. **Open your browser**
   - Navigate to `http://localhost:5000`

## Acknowledgments

- Built on top of the excellent [spotDL](https://github.com/spotDL/spotify-downloader) project