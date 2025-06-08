# I ate PDFs

Got a bloated PDF? A messy stack of documents? **Feed them to this app.**

"I ate PDFs" is a simple, modern, and lightweight utility for the Linux desktop that devours your PDF files to make them more manageable. Built with Python and GTK4/Adwaita, it provides a clean and hungry drag-and-drop interface for all its functions.

**Privacy First. Always.** "I ate PDFs" is a **local** application. All processing happens exclusively on **your computer**. Your documents are never uploaded, never shared, and never leave your control.

## Features

This app has a simple diet. It feasts on your documents to perform three core tasks:

*   **🥐 Compress:** Feeds on large, bloated PDFs and spits out lean, lightweight versions ideal for sharing.
*   **🥪 Merge:** Consumes a whole stack of separate PDF files and digests them into a single, organized document.
*   **📄 Reorder Pages:** Chews up a PDF and lets you visually reorder its pages with a simple and satisfying drag-and-drop grid.


## The Philosophy


Why build another PDF tool? Because working with PDFs on the desktop often feels like a choice between two bad options: clunky, overly-complex software or convenient online tools that come with a major catch.

The problem is a lack of simple, native PDF tools that just work. This frustration pushes many towards slick web-based services like iLovePDF. They're easy to use, but they force you into a dilemma:

> Do you upload your potentially private or sensitive documents to a third-party server?

While many online services promise security, the fundamental risk remains. Once your file leaves your machine, you lose control. For many documents, that's a risk not worth taking.

That's where **"I ate PDFs"** comes in.

This app was born from that frustration. It's built on two simple principles:

*   **Simplicity Over Bloat:** It doesn't try to be Adobe Acrobat. It focuses on the three most common PDF tasks—compressing, merging, and reordering—and does them well. No confusing menus, no unnecessary features. Just a window that's ready to eat whatever you throw at it.

*   **Privacy First. Always.** "I ate PDFs" is a **local-first** application. All processing happens exclusively on **your computer**. Your documents are never uploaded, never shared, and never leave your control. It's a simple, private, and easy-to-use PDF editor with *no strings attached*.

In short, "I ate PDFs" is for anyone who just wants to get a simple PDF job done without compromising their privacy.


## Technical Ingredients

*   **Python 3**
*   **GTK4 & Adwaita (libadwaita)** for a modern, native user interface
*   **PyPDF** for core PDF manipulation (merging, reordering)
*   **pdf2image** (with a Poppler dependency) for generating tasty page previews
*   **Ghostscript** for powerful PDF compression

## Installation
