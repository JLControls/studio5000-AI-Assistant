"""
HTML Generator Module

Generates interactive HTML documentation from parsed L5X data.
Ladder logic is drawn by a self-contained SVG renderer (see ladder_to_dot's
layout model); the only external JS dependency is vis-network (I/O diagram).
"""

import html
import json
import os
import re
import shutil
from dataclasses import asdict
# Import our modules
from .parser import Controller, Module, Program, Routine, Rung, Tag, TagUsage
from pathlib import Path
from typing import Optional

from .device_extractor import (Device, DeviceControl, DeviceExtractor,
                              DeviceSetpoint)
from .ladder_to_dot import convert_rung_to_dot, convert_rung_to_model
from .translator import translate_identifier, translate_text


class HTMLGenerator:
    """
    Generates interactive HTML documentation for L5X projects.
    
    Features:
    - Searchable tag database with cross-references
    - Interactive ladder logic diagrams (built-in SVG renderer)
    - Program and routine navigation
    - Italian to English translation
    """

    # Ladder logic is drawn by a self-contained SVG renderer (CSS/JS in assets/).
    # The only external dependency is vis-network (CDN), for the I/O network diagram.
    _VIS_NETWORK_CDN = ('<script src="https://cdnjs.cloudflare.com/ajax/libs/'
                        'vis-network/9.1.2/standalone/umd/vis-network.min.js"></script>')
    
    def __init__(
        self,
        controller: Controller,
        translate: bool = False,
        navigation_links: Optional[dict] = None,
        inline_assets: bool = False,
        bilingual: bool = False,
        use_online: bool = False,
    ):
        """
        Initialize HTML generator.

        Args:
            controller: Parsed L5X controller data
            translate: Kept for backward compatibility (deprecated; use bilingual=True).
            navigation_links: Dict of equipment names to their documentation URLs
            bilingual: Emit toggleable IT/EN bilingual HTML. When True the page
                carries <body data-lang="en">, a lang-toggle control, i18n spans
                for Italian free text, and i18n-id spans for Italian identifiers.
                __LADDER_DATA__ description fields become {en, it} objects where
                the source text is Italian.
            use_online: Pass to translate_text / translate_identifier (enable
                machine-translation fallback). False = offline / glossary only.
        """
        self.controller = controller
        self.translate = translate
        self.navigation_links = navigation_links or {}
        self.inline_assets = inline_assets
        self.bilingual = bilingual
        self.use_online = use_online

        # Extract devices
        extractor = DeviceExtractor(controller)
        self.devices = extractor.extract()

    def generate(self, output_path: Optional[Path] = None) -> str:
        """
        Generate complete HTML documentation.

        Args:
            output_path: Optional path to write the HTML file

        Returns:
            The generated HTML string
        """
        html_content = self._build_html()

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html_content, encoding='utf-8')

        return html_content

    # ------------------------------------------------------------------
    # Bilingual emitters
    # ------------------------------------------------------------------

    def _t(self, text: str) -> str:
        """HTML emitter for free text (descriptions, comments).

        When bilingual=True and the text is Italian (en != it from
        translate_text), returns a toggleable ``<span class="i18n" …>``
        carrying both languages. Otherwise returns ``html.escape(text)``.
        The returned string is always safe to embed directly in HTML — do
        NOT wrap in an additional html.escape() call.
        """
        if not text:
            return html.escape(text) if text is not None else ''
        if self.bilingual:
            en, it = translate_text(text, self.use_online)
            if en != it:
                return (
                    f'<span class="i18n" data-en="{html.escape(en)}"'
                    f' data-it="{html.escape(it)}">{html.escape(en)}</span>'
                )
        return html.escape(text)

    def _id(self, name: str) -> str:
        """HTML emitter for identifier display names (program/routine/tag names).

        When bilingual=True and the identifier is Italian (d["en"] != d["it"]),
        returns a ``<span class="i18n-id" …>``. Otherwise returns
        ``html.escape(name)``.
        Do NOT wrap the return value in html.escape() again.
        """
        if not name:
            return html.escape(name) if name is not None else ''
        if self.bilingual:
            d = translate_identifier(name, self.use_online)
            if d['en'] != d['it']:
                return (
                    f'<span class="i18n-id" data-en="{html.escape(d["en"])}"'
                    f' data-it="{html.escape(d["it"])}">{html.escape(d["en"])}</span>'
                )
        return html.escape(name)

    def _tj(self, text: str):
        """JSON emitter for free text going into ``window.__LADDER_DATA__``.

        When bilingual=True and Italian: returns ``{"en": …, "it": …}`` dict.
        Otherwise returns ``text`` (plain string). The return value is passed
        directly to json.dumps — never escape it further.
        """
        if not text:
            return text
        if self.bilingual:
            en, it = translate_text(text, self.use_online)
            if en != it:
                return {"en": en, "it": it}
        return text

    def _idj(self, name: str):
        """JSON emitter for identifier display names going into ``window.__LADDER_DATA__``.

        When bilingual=True and Italian: returns ``{"en": …, "it": …}`` dict.
        Otherwise returns ``name`` (plain string).
        """
        if not name:
            return name
        if self.bilingual:
            d = translate_identifier(name, self.use_online)
            if d['en'] != d['it']:
                return {"en": d["en"], "it": d["it"]}
        return name

    def _icon(self, symbol: str, cls: str = "icon") -> str:
        """Return an inline SVG use element for the embedded MDI sprite."""
        return f'<svg class="{cls}"><use href="#{symbol}"></use></svg>'

    def _get_mdi_sprite(self) -> str:
        """Embed the MDI sprite inline for full portability."""
        return '''<svg xmlns="http://www.w3.org/2000/svg" style="display:none">
  <symbol id="mdi-information" viewBox="0 0 24 24"><path fill="currentColor" d="M13,9H11V7H13M13,17H11V11H13M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z"/></symbol>
  <symbol id="mdi-overview" viewBox="0 0 24 24"><path fill="currentColor" d="M19,5V19H5V5H19M19,3H5A2,2 0 0,0 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5A2,2 0 0,0 19,3M7,7H9V9H7V7M7,11H9V17H7V11M11,7H17V9H11V7M11,11H17V13H11V11M11,15H17V17H11V15Z"/></symbol>
  <symbol id="mdi-monitor" viewBox="0 0 24 24"><path fill="currentColor" d="M4,6H20V16H4M20,18A2,2 0 0,0 22,16V6C22,4.89 21.1,4 20,4H4C2.89,4 2,4.89 2,6V16A2,2 0 0,0 4,18H0V20H24V18H20Z"/></symbol>
  <symbol id="mdi-chart-bar" viewBox="0 0 24 24"><path fill="currentColor" d="M22,21H2V3H4V19H6V10H10V19H12V6H16V19H18V14H22V21Z"/></symbol>
  <symbol id="mdi-network" viewBox="0 0 24 24"><path fill="currentColor" d="M17,3A2,2 0 0,1 19,5V15A2,2 0 0,1 17,17H13V19H14A1,1 0 0,1 15,20H22V22H15A1,1 0 0,1 14,23H10A1,1 0 0,1 9,22H2V20H9A1,1 0 0,1 10,19H11V17H7A2,2 0 0,1 5,15V5A2,2 0 0,1 7,3H17M7,5V15H17V5H7M8,6H10V8H8V6M8,9H10V14H8V9M11,9H13V14H11V9M14,9H16V14H14V9Z"/></symbol>
  <symbol id="mdi-tag" viewBox="0 0 24 24"><path fill="currentColor" d="M5.5,7A1.5,1.5 0 0,1 4,5.5A1.5,1.5 0 0,1 5.5,4A1.5,1.5 0 0,1 7,5.5A1.5,1.5 0 0,1 5.5,7M21.41,11.58L12.41,2.58C12.05,2.22 11.55,2 11,2H4C2.89,2 2,2.89 2,4V11C2,11.55 2.22,12.05 2.59,12.41L11.58,21.41C11.95,21.77 12.45,22 13,22C13.55,22 14.05,21.77 14.41,21.41L21.41,14.41C21.78,14.05 22,13.55 22,13C22,12.44 21.77,11.94 21.41,11.58Z"/></symbol>
  <symbol id="mdi-thermometer" viewBox="0 0 24 24"><path fill="currentColor" d="M7,2V4H8V18A4,4 0 0,0 12,22A4,4 0 0,0 16,18V4H17V2H7M11,16C10.4,16 10,15.6 10,15C10,14.4 10.4,14 11,14C11.6,14 12,14.4 12,15C12,15.6 11.6,16 11,16M13,12C12.4,12 12,11.6 12,11C12,10.4 12.4,10 13,10C13.6,10 14,10.4 14,11C14,11.6 13.6,12 13,12M13,8C12.4,8 12,7.6 12,7C12,6.4 12.4,6 13,6C13.6,6 14,6.4 14,7C14,7.6 13.6,8 13,8Z"/></symbol>
  <symbol id="mdi-alert" viewBox="0 0 24 24"><path fill="currentColor" d="M13,14H11V10H13M13,18H11V16H13M1,21H23L12,2L1,21Z"/></symbol>
  <symbol id="mdi-magnify-plus" viewBox="0 0 24 24"><path fill="currentColor" d="M15.5,14L20.5,19L19,20.5L14,15.5V14.71L13.73,14.43C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.43,13.73L14.71,14H15.5M9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14M12,10H10V12H9V10H7V9H9V7H10V9H12V10Z"/></symbol>
  <symbol id="mdi-magnify-minus" viewBox="0 0 24 24"><path fill="currentColor" d="M15.5,14L20.5,19L19,20.5L14,15.5V14.71L13.73,14.43C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.43,13.73L14.71,14H15.5M9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14M7,9H12V10H7V9Z"/></symbol>
  <symbol id="mdi-restore" viewBox="0 0 24 24"><path fill="currentColor" d="M12,6V9L16,5L12,1V4A8,8 0 0,0 4,12C4,13.57 4.46,15.03 5.24,16.26L6.7,14.8C6.25,13.97 6,13 6,12A6,6 0 0,1 12,6M18.76,7.74L17.3,9.2C17.74,10.04 18,11 18,12A6,6 0 0,1 12,18V15L8,19L12,23V20A8,8 0 0,0 20,12C20,10.43 19.54,8.97 18.76,7.74Z"/></symbol>
  <symbol id="mdi-eye" viewBox="0 0 24 24"><path fill="currentColor" d="M12,9A3,3 0 0,1 15,12A3,3 0 0,1 12,15A3,3 0 0,1 9,12A3,3 0 0,1 12,9M12,4.5C17,4.5 21.27,7.61 23,12C21.27,16.39 17,19.5 12,19.5C7,19.5 2.73,16.39 1,12C2.73,7.61 7,4.5 12,4.5M3.18,12C4.83,15.36 8.24,17.5 12,17.5C15.76,17.5 19.17,15.36 20.82,12C19.17,8.64 15.76,6.5 12,6.5C8.24,6.5 4.83,8.64 3.18,12Z"/></symbol>
  <symbol id="mdi-eye-off" viewBox="0 0 24 24"><path fill="currentColor" d="M11.83,9L15,12.16C15,12.11 15,12.05 15,12A3,3 0 0,0 12,9C11.94,9 11.89,9 11.83,9M7.53,9.8L9.08,11.35C9.03,11.56 9,11.77 9,12A3,3 0 0,0 12,15C12.22,15 12.44,14.97 12.65,14.92L14.2,16.47C13.53,16.8 12.79,17 12,17A5,5 0 0,1 7,12C7,11.21 7.2,10.47 7.53,9.8M2,4.27L4.28,6.55L4.73,7C3.08,8.3 1.78,10 1,12C2.73,16.39 7,19.5 12,19.5C13.55,19.5 15.03,19.2 16.38,18.66L16.81,19.08L19.73,22L21,20.73L3.27,3M12,7A5,5 0 0,1 17,12C17,12.64 16.87,13.26 16.64,13.82L19.57,16.75C21.07,15.5 22.27,13.86 23,12C21.27,7.61 17,4.5 12,4.5C10.6,4.5 9.26,4.75 8,5.2L10.17,7.35C10.74,7.13 11.35,7 12,7Z"/></symbol>
  <symbol id="mdi-chevron-right" viewBox="0 0 24 24"><path fill="currentColor" d="M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z"/></symbol>
  <symbol id="mdi-clipboard" viewBox="0 0 24 24"><path fill="currentColor" d="M19,3H14.82C14.4,1.84 13.3,1 12,1C10.7,1 9.6,1.84 9.18,3H5A2,2 0 0,0 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5A2,2 0 0,0 19,3M12,3A1,1 0 0,1 13,4A1,1 0 0,1 12,5A1,1 0 0,1 11,4A1,1 0 0,1 12,3"/></symbol>
  <symbol id="mdi-clipboard-outline" viewBox="0 0 24 24"><path fill="currentColor" d="M19,3H14.82C14.4,1.84 13.3,1 12,1C10.7,1 9.6,1.84 9.18,3H5A2,2 0 0,0 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5A2,2 0 0,0 19,3M12,3A1,1 0 0,1 13,4A1,1 0 0,1 12,5A1,1 0 0,1 11,4A1,1 0 0,1 12,3M19,19H5V5H7V7H17V5H19V19Z"/></symbol>
  <symbol id="mdi-folder" viewBox="0 0 24 24"><path fill="currentColor" d="M10,4H4C2.89,4 2,4.89 2,6V18A2,2 0 0,0 4,20H20A2,2 0 0,0 22,18V8C22,6.89 21.1,6 20,6H12L10,4Z"/></symbol>
  <symbol id="mdi-wrench" viewBox="0 0 24 24"><path fill="currentColor" d="M22.7,19L13.6,9.9C14.5,7.6 14,4.9 12.1,3C10.1,1 7.1,0.6 4.7,1.7L9,6L6,9L1.6,4.7C0.4,7.1 0.9,10.1 2.9,12.1C4.8,14 7.5,14.5 9.8,13.6L18.9,22.7C19.3,23.1 19.9,23.1 20.3,22.7L22.6,20.4C23.1,20 23.1,19.3 22.7,19Z"/></symbol>
  <symbol id="mdi-engine" viewBox="0 0 24 24"><path fill="currentColor" d="M7,4V6H10V8H7L5,10V13H3V10H1V18H3V15H5V18H8L10,20H18V16H20V19H23V9H20V12H18V8H12V6H15V4H7Z"/></symbol>
  <symbol id="mdi-arrow-expand" viewBox="0 0 24 24"><path fill="currentColor" d="M10,21V19H6.41L10.91,14.5L9.5,13.09L5,17.59V14H3V21H10M14.5,10.91L19,6.41V10H21V3H14V5H17.59L13.09,9.5L14.5,10.91Z"/></symbol>
</svg>'''

    def _get_inline_scripts(self) -> str:
        """External scripts for inline-asset mode.

        The ladder renderer is self-contained, so the only external dependency
        is vis-network (for the I/O network diagram), referenced from its CDN.
        """
        return self._VIS_NETWORK_CDN
    
    def _build_html(self) -> str:
        """Build the complete HTML document."""
        scripts_html = '            ' + self._VIS_NETWORK_CDN
        # <body> and the lang-toggle control are only emitted for bilingual
        # docs; a non-bilingual doc's <body> line stays exactly what the
        # pre-bilingual generator emitted (no stray blank line from an empty
        # lang-toggle placeholder either).
        body_open = (
            '''<body data-lang="en">
    <div class="lang-toggle" id="lang-toggle" role="group" aria-label="Language">
      <button type="button" class="lang-btn active" data-lang="en">EN</button>
      <button type="button" class="lang-btn" data-lang="it">IT</button>
    </div>'''
            if self.bilingual else '<body>'
        )
        return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(self.controller.name)} - L5X Documentation</title>

    <!-- vis-network for the I/O network diagram (ladder logic uses a built-in SVG renderer) -->
{scripts_html}

    <style>
{self._get_styles()}
    </style>
    {self._get_mdi_sprite()}
</head>
{body_open}
    <div class="app-container">
        <!-- Sidebar Navigation -->
        <nav class="sidebar">
            <div class="sidebar-header">
                <div class="nav-buttons">
                    <button class="nav-btn" onclick="navigateBack()" title="Back" id="btn-back" disabled>
                        <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z"/></svg>
                    </button>
                    <button class="nav-btn" onclick="navigateForward()" title="Forward" id="btn-forward" disabled>
                        <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M4,11V13H16L10.5,18.5L11.92,19.92L19.84,12L11.92,4.08L10.5,5.5L16,11H4Z"/></svg>
                    </button>
                    <button class="nav-btn" onclick="toggleSidebar()" title="Toggle Sidebar" id="btn-toggle-sidebar">
                        <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"/></svg>
                    </button>
                </div>
                <h1><svg class="icon"><use href="#mdi-clipboard-outline"></use></svg> {html.escape(self.controller.name)}</h1>
                <p class="processor">{html.escape(self.controller.processor_type)}</p>
                <p class="version">v{self.controller.major_rev}.{self.controller.minor_rev}</p>
                <p class="ip-address">{self._extract_ip_from_controller()}</p>
            </div>

            <div class="nav-search">
                <svg class="icon icon-sm nav-search-icon"><use href="#mdi-magnify-plus"></use></svg>
                <input type="text" id="nav-search" placeholder="Filter programs, routines, AOIs…"
                       oninput="filterNav(this.value)" autocomplete="off" spellcheck="false">
                <button class="nav-search-clear" type="button" onclick="clearNavSearch()" title="Clear" aria-label="Clear filter">&times;</button>
            </div>

            <div class="nav-section equipment-nav-section">
                <div class="project-nav-header collapsed" onclick="toggleProjectNav(this)">
                    <svg class="icon" style="width: 1.2em; height: 1.2em; margin-right: 0.3em;"><use href="#mdi-chevron-right"></use></svg>
                    <h3><span style="display: inline-block; margin-bottom: -0.1em;"><svg class="icon" style="width: 1em; height: 1em; margin-right: 0.2em; vertical-align: -0.15em;"><use href="#mdi-folder"></use></svg>Other Equipment</span></h3>
                </div>
                <div class="project-nav-content collapsed">
                    <ul>
{self._build_equipment_nav()}
                    </ul>
                </div>
            </div>
            
            <div class="nav-section">
                <div class="project-nav-header expanded" onclick="toggleProjectNav(this)">
                    <svg class="icon" style="width: 1.2em; height: 1.2em; margin-right: 0.3em;"><use href="#mdi-chevron-right"></use></svg>
                    <h3><span style="display: inline-block; margin-bottom: -0.1em;"><svg class="icon" style="width: 1em; height: 1em; margin-right: 0.2em; vertical-align: -0.15em;"><use href="#mdi-information"></use></svg>Summary</span></h3>
                </div>
                <div class="project-nav-content">
                    <ul>
                        <li><a href="#overview" onclick="showSection('overview')"><svg class="icon icon-sm"><use href="#mdi-information"></use></svg> Project Info</a></li>
                        <li><a href="#devices" onclick="showSection('devices')"><svg class="icon icon-sm"><use href="#mdi-engine"></use></svg> Devices</a></li>
                        <li><a href="#tags" onclick="showSection('tags')"><svg class="icon icon-sm"><use href="#mdi-tag"></use></svg> Tag Database</a></li>
                        <li><a href="#datatypes" onclick="showSection('datatypes')"><svg class="icon icon-sm"><use href="#mdi-overview"></use></svg> Data Types</a></li>
                        <li><a href="#modules" onclick="showSection('modules')"><svg class="icon icon-sm"><use href="#mdi-network"></use></svg> I/O Modules</a></li>
                        <li><a href="#io-points" onclick="showSection('io-points')"><svg class="icon icon-sm"><use href="#mdi-monitor"></use></svg> I/O Points</a></li>
                        <li><a href="#alarms" onclick="showSection('alarms')"><svg class="icon icon-sm"><use href="#mdi-alert"></use></svg> Alarms</a></li>
                    </ul>
                </div>
            </div>
            
            <div class="nav-section">
                <div class="project-nav-header collapsed" onclick="toggleProjectNav(this)">
                    <svg class="icon" style="width: 1.2em; height: 1.2em; margin-right: 0.3em;"><use href="#mdi-chevron-right"></use></svg>
                    <h3><span style="display: inline-block; margin-bottom: -0.1em;"><svg class="icon" style="width: 1em; height: 1em; margin-right: 0.2em; vertical-align: -0.15em;"><use href="#mdi-folder"></use></svg>Programs</span></h3>
                </div>
                <div class="project-nav-content collapsed">
                    <ul>
{self._build_program_nav()}
                    </ul>
                </div>
            </div>
            
            <div class="nav-section">
                <div class="project-nav-header collapsed" onclick="toggleProjectNav(this)">
                    <svg class="icon" style="width: 1.2em; height: 1.2em; margin-right: 0.3em;"><use href="#mdi-chevron-right"></use></svg>
                    <h3><span style="display: inline-block; margin-bottom: -0.1em;"><svg class="icon" style="width: 1em; height: 1em; margin-right: 0.2em; vertical-align: -0.15em;"><use href="#mdi-wrench"></use></svg>Add-On Instructions</span></h3>
                </div>
                <div class="project-nav-content collapsed">
                    <ul>
{self._build_aoi_nav()}
                    </ul>
                </div>
            </div>
        </nav>
        
        <!-- Main Content -->
        <main class="content">
            <!-- Sticky breadcrumb + jump bar -->
            <div id="crumbbar">
                <nav id="crumbs" aria-label="Breadcrumb">
                    <span class="crumb-ctl">{html.escape(self.controller.name)}</span>
                </nav>
                <div class="crumb-tools">
                    <label class="rung-jump" title="Jump to rung number in the current routine">
                        <span>Rung</span>
                        <input type="text" id="rung-jump" inputmode="numeric" placeholder="#"
                               onkeydown="if(event.key==='Enter')jumpToRungNumber(this.value)">
                    </label>
                    <div class="global-jump">
                        <input type="text" id="global-jump" autocomplete="off" spellcheck="false"
                               placeholder="Go to tag or routine…"
                               oninput="globalJump(this.value)" onkeydown="globalJumpKey(event)"
                               onblur="setTimeout(hideGlobalJump,150)">
                        <div id="global-jump-results"></div>
                    </div>
                </div>
            </div>
            <!-- Floating right rail: per-routine tag browser (top) + minimap (bottom) -->
            <div id="right-rail" aria-hidden="true">
                <aside id="tagbrowser" class="tag-browser">
                    <div class="tb-head">
                        <button class="tb-toggle" onclick="toggleTagBrowser(this)" title="Collapse / expand">
                            <svg class="icon icon-sm tb-chev"><use href="#mdi-chevron-right"></use></svg>
                            <span class="tb-title">Tags <span class="tb-count">0</span></span>
                        </button>
                        <button class="tb-colorize" onclick="toggleColorize(this)" title="Color components by tag">Colorize</button>
                    </div>
                    <div class="tb-list"></div>
                </aside>
                <div id="minimap">
                    <div id="minimap-track" title="Routine overview — click to jump">
                        <div id="minimap-inner"></div>
                        <div id="minimap-viewport"></div>
                    </div>
                </div>
            </div>
            <!-- Overview Section -->
            <section id="overview" class="section active">
                <h2><svg class="icon icon-lg"><use href="#mdi-information"></use></svg> Project Overview</h2>
                <div class="info-grid">
                    <div class="info-card">
                        <h4><svg class="icon"><use href="#mdi-monitor"></use></svg> Controller</h4>
                        <p><strong>Name:</strong> {html.escape(self.controller.name)}</p>
                        <p><strong>Processor:</strong> {html.escape(self.controller.processor_type)}</p>
                        <p><strong>Revision:</strong> {self.controller.major_rev}.{self.controller.minor_rev}</p>
                        <p><strong>Software:</strong> {html.escape(self.controller.software_revision)}</p>
                        <p><strong>Exported:</strong> {html.escape(self.controller.export_date)}</p>
                    </div>
                    <div class="info-card">
                        <h4><svg class="icon"><use href="#mdi-chart-bar"></use></svg> Statistics</h4>
                        <p><strong>Programs:</strong> {len(self.controller.programs)}</p>
                        <p><strong>Controller Tags:</strong> {len(self.controller.controller_tags)}</p>
                        <p><strong>Data Types:</strong> {len(self.controller.data_types)}</p>
                        <p><strong>AOIs:</strong> {len(self.controller.add_on_instructions)}</p>
                        <p><strong>I/O Modules:</strong> {len(self.controller.modules)}</p>
                    </div>
                    <div class="info-card">
                        <h4><svg class="icon"><use href="#mdi-network"></use></svg> Network</h4>
                        <p><strong>Comm Path:</strong> {html.escape(self.controller.comm_path) if self.controller.comm_path else 'N/A'}</p>
                        <p><strong>Ethernet Mode:</strong> {html.escape(self.controller.ethernet_mode) if self.controller.ethernet_mode else 'N/A'}</p>
                    </div>
                </div>
                
                <!-- Network Diagram -->
{self._build_network_diagram_section()}
                
                <!-- Ethernet Devices -->
{self._build_ethernet_devices_section()}
            </section>
            
            {self._build_device_section()}
            
            <!-- Tag Database Section -->
            <section id="tags" class="section">
                <h2><svg class="icon icon-lg"><use href="#mdi-tag"></use></svg> Tag Database</h2>
                <div class="search-box">
                    <input type="text" id="tag-search" placeholder="Search tags..." oninput="filterTags()">
                    <select id="scope-filter" onchange="filterTags()">
                        <option value="">All Scopes</option>
                        <option value="Controller">Controller</option>
{self._build_scope_options()}
                    </select>
                    <select id="usage-filter" onchange="filterTags()">
                        <option value="">All Usage Types</option>
                        <option value="read">Read Only</option>
                        <option value="destructive">Destructive</option>
                    </select>
                </div>
                <div class="table-container">
                    <table id="tag-table" class="data-table">
                        <thead>
                            <tr>
                                <th onclick="sortTable('tag-table', 0)">Name ↕</th>
                                <th onclick="sortTable('tag-table', 1)">Data Type ↕</th>
                                <th onclick="sortTable('tag-table', 2)">Scope ↕</th>
                                <th onclick="sortTable('tag-table', 3)">Description</th>
                                <th>Usages</th>
                            </tr>
                        </thead>
                        <tbody>
{self._build_tag_rows()}
                        </tbody>
                    </table>
                </div>
            </section>
            
            <!-- Data Types Section -->
            <section id="datatypes" class="section">
                <h2>User-Defined Data Types</h2>
                <div class="card-grid">
{self._build_datatype_cards()}
                </div>
            </section>
            
            <!-- I/O Modules Section -->
            <section id="modules" class="section">
                <h2>I/O Modules</h2>
                <div class="table-container">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Catalog Number</th>
                                <th>Slot/Address</th>
                                <th>Parent</th>
                                <th>IP Address</th>
                                <th>I/O Points</th>
                            </tr>
                        </thead>
                        <tbody>
{self._build_module_rows()}
                        </tbody>
                    </table>
                </div>
            </section>
            
            <!-- I/O Points Section -->
            <section id="io-points" class="section">
                <h2><svg class="icon icon-lg"><use href="#mdi-thermometer"></use></svg> I/O Points</h2>
                <p class="section-description">Complete list of all input and output points. Click any point to see cross-reference. Unused points are marked as <span class="io-spare-badge">SPARE</span>.</p>
                <div class="search-box">
                    <input type="text" id="io-search" placeholder="Search I/O points..." oninput="filterIOPoints()">
                    <select id="io-type-filter" onchange="filterIOPoints()">
                        <option value="">All Types</option>
                        <option value="Input">Inputs</option>
                        <option value="Output">Outputs</option>
                    </select>
                    <select id="io-usage-filter" onchange="filterIOPoints()">
                        <option value="">All Usage</option>
                        <option value="used">Used</option>
                        <option value="spare">Spare</option>
                    </select>
                </div>
{self._build_io_points_content()}
            </section>
            
            <!-- Alarms Section -->
            <section id="alarms" class="section">
                <h2><svg class="icon icon-lg"><use href="#mdi-alert"></use></svg> Alarm Summary</h2>
                <p class="section-description">Summary of all alarm-related logic in the project, including fault detection and alarm handling.</p>
                <div class="search-box">
                    <input type="text" id="alarm-search" placeholder="Search alarms..." oninput="filterAlarms()">
                </div>
                <div class="table-container">
                    <table id="alarm-table" class="data-table">
                        <thead>
                            <tr>
                                <th onclick="sortTable('alarm-table', 0)">Tag Name ↕</th>
                                <th onclick="sortTable('alarm-table', 1)">Type ↕</th>
                                <th>Description</th>
                                <th>Location</th>
                            </tr>
                        </thead>
                        <tbody>
{self._build_alarm_rows()}
                        </tbody>
                    </table>
                </div>
            </section>
            
            <!-- Program Sections -->
{self._build_program_sections()}
            
            <!-- AOI Sections -->
{self._build_aoi_sections()}
            
            <!-- Tag Usage Modal -->
            <div id="usage-modal" class="modal">
                <div class="modal-content">
                    <span class="close" onclick="closeModal()">&times;</span>
                    <h3 id="modal-title">Tag Usage</h3>
                    <div id="modal-body"></div>
                </div>
            </div>
            
            <!-- Ladder Diagram Modal -->
            <div id="ladder-modal" class="modal">
                <div class="modal-content ladder-modal-content">
                    <span class="close" onclick="closeLadderModal()">&times;</span>
                    <h3 id="ladder-modal-title">Ladder Logic</h3>
                    <div class="ladder-controls">
                        <button onclick="zoomIn()"><svg class="icon"><use href="#mdi-magnify-plus"></use></svg></button>
                        <button onclick="zoomOut()"><svg class="icon"><use href="#mdi-magnify-minus"></use></svg></button>
                        <button onclick="resetZoom()"><svg class="icon"><use href="#mdi-restore"></use></svg></button>
                    </div>
                    <div id="ladder-container" class="ladder-container"></div>
                </div>
            </div>
        </main>
    </div>
    
    <script>
{self._get_scripts()}
    </script>
</body>
</html>'''
    
    def _get_styles(self) -> str:
        """CSS for the document (assets/styles.css).

        assets/i18n.css (the language-toggle control styling) is appended
        only for bilingual docs, so non-bilingual output's CSS stays
        byte-identical to the pre-bilingual-feature generator.
        """
        css = self._read_asset('styles.css')
        if self.bilingual:
            css += chr(10) + self._read_asset('i18n.css')
        return css

    @staticmethod
    def _read_asset(relpath: str) -> str:
        """Read a CSS/JS template bundled beside this module under assets/."""
        return (Path(__file__).resolve().parent / 'assets' / relpath).read_text(encoding='utf-8')

    # Marker syntax embedded in assets/js/*.js at the handful of spots where a
    # renderer that is otherwise byte-identical to the pre-bilingual generator
    # needs a bilingual-only variant (a pickLang() wrapper, a rerenderForLang()
    # hook, …):
    #   /*I18N-BI-START*/ …lines present only in bilingual docs… /*I18N-BI-END*/
    #   /*I18N-BASE-START*/ …lines present only in non-bilingual docs… /*I18N-BASE-END*/
    # Each marker sits alone on its own line. `_apply_i18n_markers` drops the
    # block that doesn't match self.bilingual (marker lines and content,
    # including their own newlines) and, for the block that does match, drops
    # just the two marker lines and keeps the content — so non-bilingual
    # output is exactly the pre-bilingual source text (no leftover
    # pickLang/i18n references, no stray blank lines) while bilingual output
    # gets the toggle-aware code. See 10-navigation.js for a worked example.
    _I18N_BI_RE = re.compile(r'^[ \t]*/\*I18N-BI-START\*/\n(.*?)^[ \t]*/\*I18N-BI-END\*/\n', re.M | re.S)
    _I18N_BASE_RE = re.compile(r'^[ \t]*/\*I18N-BASE-START\*/\n(.*?)^[ \t]*/\*I18N-BASE-END\*/\n', re.M | re.S)

    def _apply_i18n_markers(self, text: str) -> str:
        """Resolve I18N-BI/I18N-BASE marker blocks to the variant matching
        self.bilingual (see _I18N_BI_RE/_I18N_BASE_RE above)."""
        if self.bilingual:
            text = self._I18N_BI_RE.sub(lambda m: m.group(1), text)
            text = self._I18N_BASE_RE.sub('', text)
        else:
            text = self._I18N_BI_RE.sub('', text)
            text = self._I18N_BASE_RE.sub(lambda m: m.group(1), text)
        return text

    def _read_js_bundle(self) -> str:
        """Concatenate the JS modules (assets/js/NN-*.js) in filename order into a
        single script body. They share one global scope (one <script> block), so
        order matters — hence the numeric prefixes.

        assets/js/05-i18n.js (the language-toggle engine) is skipped for
        non-bilingual docs, and any /*I18N-BI-START*/…/*I18N-BI-END*/ /
        /*I18N-BASE-START*/…/*I18N-BASE-END*/ span pair in the remaining files
        is resolved to its non-bilingual variant, so their JS bundle stays
        byte-identical to the pre-bilingual-feature generator.
        """
        js_dir = Path(__file__).resolve().parent / 'assets' / 'js'
        return ''.join(self._apply_i18n_markers(f.read_text(encoding='utf-8'))
                       for f in sorted(js_dir.glob('*.js'))
                       if self.bilingual or f.name != '05-i18n.js')
    
    def _get_scripts(self) -> str:
        """Get JavaScript code."""
        # Build UDT member description lookup
        udt_member_descriptions = {}
        for udt in self.controller.data_types:
            udt_members = {}
            for member in udt.members:
                if member.description:
                    udt_members[member.name] = self._tj(member.description)
            if udt_members:
                udt_member_descriptions[udt.name] = udt_members

        # Build tag data for JavaScript with UDT member descriptions
        tag_data = []
        for tag in self.controller.controller_tags:
            # Get description — _tj returns a plain string or {en,it} dict
            description = self._tj(tag.description)

            # For tags that are UDT instances, build member descriptions
            member_descriptions = {}
            if tag.data_type in udt_member_descriptions:
                member_descriptions = udt_member_descriptions[tag.data_type]

            tag_data.append({
                'name': tag.name,
                'dataType': tag.data_type,
                'description': description,
                'memberDescriptions': member_descriptions,
                'usages': [
                    {
                        'program': u.program,
                        'routine': u.routine,
                        'rung': u.rung_number,
                        'type': u.usage_type,
                        'instruction': u.instruction,
                        'ref': u.ref
                    }
                    for u in tag.usages
                ]
            })

        # Add program-scoped tags
        for program in self.controller.programs:
            for tag in program.local_tags:
                description = self._tj(tag.description)
                member_descriptions = {}
                if tag.data_type in udt_member_descriptions:
                    member_descriptions = udt_member_descriptions[tag.data_type]

                tag_data.append({
                    'name': tag.name,
                    'dataType': tag.data_type,
                    'description': description,
                    'memberDescriptions': member_descriptions,
                    'usages': [
                        {
                            'program': u.program,
                            'routine': u.routine,
                            'rung': u.rung_number,
                            'type': u.usage_type,
                            'instruction': u.instruction,
                            'ref': u.ref
                        }
                        for u in tag.usages
                    ]
                })

        # Build rung data for ladder visualization
        rung_data = {}

        # Build AOI parameter map for call-block labeling:
        #   {AOI_NAME: [required parameter names, in document order]}
        # An AOI call's arguments (after the instance tag) are exactly the
        # Required parameters, in document order (InOut params are always
        # Required), so zipping operands[1:] with this list labels each argument.
        aoi_params = {}
        for aoi in self.controller.add_on_instructions:
            required_names = [p.name for p in aoi.parameters if p.required]
            if required_names:
                aoi_params[aoi.name] = required_names

        # Build AOI identifier display map for ladder call-block headers:
        #   {AOI_NAME: bilingual-capable display value (self._idj() output)}
        # An AOI call block's "head" is the AOI's own identifier, so it gets
        # the same treatment as tag/program/routine identifiers elsewhere.
        aoi_id_display = {aoi.name: self._idj(aoi.name) for aoi in self.controller.add_on_instructions}

        # Build controller tag descriptions map.
        # KEYs (tag.name / operand) are raw identifiers — stay native.
        # VALUEs are translated via _tj: plain string or {en,it} dict.
        controller_descriptions = {}
        for tag in self.controller.controller_tags:
            if tag.description:
                controller_descriptions[tag.name] = self._tj(tag.description)

        # Add controller-scoped comments (tag member descriptions)
        if hasattr(self.controller, 'comments'):
            for operand, comment in self.controller.comments.items():
                controller_descriptions[operand] = self._tj(comment)

        for program in self.controller.programs:
            # Merge with program tags
            program_descriptions = controller_descriptions.copy()
            for tag in program.local_tags:
                if tag.description:
                    program_descriptions[tag.name] = self._tj(tag.description)

            # Add program-scoped comments
            if hasattr(program, 'comments'):
                for operand, comment in program.comments.items():
                    program_descriptions[operand] = self._tj(comment)

            for routine in program.routines:
                for rung in routine.rungs:
                    key = f"{program.name}_{routine.name}_{rung.number}"
                    try:
                        rung_data[key] = convert_rung_to_model(rung.text, rung.number, rung.comment, program_descriptions, aoi_params, aoi_id_display)
                    except Exception:
                        rung_data[key] = None

        for aoi in self.controller.add_on_instructions:
            # Use controller descriptions for AOIs
            aoi_descriptions = controller_descriptions.copy()
            for routine in aoi.routines:
                for rung in routine.rungs:
                    key = f"AOI_{aoi.name}_{routine.name}_{rung.number}"
                    try:
                        rung_data[key] = convert_rung_to_model(rung.text, rung.number, rung.comment, aoi_descriptions, aoi_params, aoi_id_display)
                    except Exception:
                        rung_data[key] = None
        
        # Add system tags/instructions descriptions (Rockwell standard tags)
        system_tags = [
            # System instructions
            {'name': 'GSV', 'dataType': 'Instruction', 'description': 'Get System Value - Retrieves controller/module status, time, or configuration data.'},
            {'name': 'SSV', 'dataType': 'Instruction', 'description': 'Set System Value - Modifies controller/module settings or configuration data.'},
            {'name': 'MSG', 'dataType': 'Instruction', 'description': 'Message - Sends data to or receives data from another controller or device.'},
            # Status file bits (S:FS equivalent)
            {'name': 'S:FS', 'dataType': 'BOOL', 'description': 'First Scan - True only during the first scan after entering Run mode.'},
            {'name': 'S:N', 'dataType': 'BOOL', 'description': 'Negative Flag - Indicates result of last math operation was negative.'},
            {'name': 'S:Z', 'dataType': 'BOOL', 'description': 'Zero Flag - Indicates result of last math operation was zero.'},
            {'name': 'S:V', 'dataType': 'BOOL', 'description': 'Overflow Flag - Indicates overflow condition in math operation.'},
            {'name': 'S:C', 'dataType': 'BOOL', 'description': 'Carry Flag - Indicates carry out of most significant bit.'},
            # Wall clock tags
            {'name': 'LocalDateTime', 'dataType': 'DINT[7]', 'description': 'Local Date/Time - Controller local time as [Year, Month, Day, Hour, Minute, Second, Microseconds].'},
            {'name': 'WallClockTime', 'dataType': 'LINT', 'description': 'Wall Clock Time - Current time in microseconds since 1970-01-01 (UTC).'},
            # Controller status
            {'name': 'ControllerDevice', 'dataType': 'STRUCT', 'description': 'Controller Device - Contains controller hardware information and status.'},
        ]
        
        for sys_tag in system_tags:
            if not any(t['name'] == sys_tag['name'] for t in tag_data):
                tag_data.append({
                    'name': sys_tag['name'],
                    'dataType': sys_tag['dataType'],
                    'description': sys_tag['description'],
                    'memberDescriptions': {},
                    'usages': []
                })

        # Routine index for the global "go to" jump box.
        # displayRoutine/displayProgram (the bilingual-aware display names the
        # jump box reads via pickLang()) are added only for bilingual docs —
        # a non-bilingual doc's __LADDER_DATA__ keeps exactly the pre-bilingual
        # shape, and 10-navigation.js's non-bilingual code path reads the raw
        # program/routine fields directly instead.
        routine_index = []
        for program in self.controller.programs:
            for routine in program.routines:
                entry = {
                    'program': program.name,
                    'routine': routine.name,
                    'section': f'program-{program.name}',
                    'type': routine.routine_type,
                    'rungs': len(routine.rungs),
                    'kind': 'program',
                }
                if self.bilingual:
                    entry['displayRoutine'] = self._idj(routine.name)
                    entry['displayProgram'] = self._idj(program.name)
                routine_index.append(entry)
        for aoi in self.controller.add_on_instructions:
            for routine in aoi.routines:
                entry = {
                    'program': aoi.name,
                    'routine': routine.name,
                    'section': f'aoi-{aoi.name}',
                    'type': routine.routine_type,
                    'rungs': len(routine.rungs),
                    'kind': 'aoi',
                }
                if self.bilingual:
                    entry['displayRoutine'] = self._idj(routine.name)
                    entry['displayProgram'] = self._idj(aoi.name)
                routine_index.append(entry)

        # Ladder/UI behaviour is authored in assets/js/*.js (concatenated as
        # app.js); the page-specific data is injected as a single global so the
        # JS stays clean, lintable template code with no Python interpolation.
        network_tree = getattr(self, 'network_tree_data', self._build_network_tree_data())
        ladder_data = {
            'tagData': tag_data,
            'routineIndex': routine_index,
            'rungData': rung_data,
            'networkTree': network_tree,
        }
        return ('window.__LADDER_DATA__ = ' + json.dumps(ladder_data) + ';' + chr(10)
                + self._read_js_bundle())
    
    def _build_program_nav(self) -> str:
        """Build program navigation items with routine tree view."""
        lines = []
        for program in sorted(self.controller.programs,
                              key=lambda p: translate_identifier(p.name, self.use_online)['en'].lower()):
            name = self._id(program.name)          # HTML-safe; may be bilingual span
            program_id = html.escape(program.name) # raw identifier for section IDs / JS args
            lines.append(f'                    <li class="tree-item">')
            lines.append(f'                        <div class="tree-header" onclick="toggleTree(this)">')
            lines.append(f'                            <span class="tree-toggle"><svg class="icon"><use href="#mdi-chevron-right"></use></svg></span>')
            lines.append(f'                            <a href="#program-{program_id}" '
                        f'onclick="event.stopPropagation(); showSection(\'program-{program_id}\')">')
            lines.append(f'                                {name}')
            lines.append(f'                            </a>')
            lines.append(f'                        </div>')
            lines.append(f'                        <ul class="tree-children">')
            for routine in program.routines:
                routine_name = self._id(routine.name)  # HTML-safe; may be bilingual span
                routine_sec = f'routine-{program_id}-{html.escape(routine.name)}'
                lines.append(f'                            <li>')
                lines.append(f'                                <a href="#{routine_sec}" '
                            f'onclick="showSection(\'{routine_sec}\')">')
                lines.append(f'                                    <svg class="icon icon-sm"><use href="#mdi-clipboard"></use></svg> {routine_name}')
                lines.append(f'                                </a>')
                lines.append(f'                            </li>')
            lines.append(f'                        </ul>')
            lines.append(f'                    </li>')
        return '\n'.join(lines)
    
    def _build_aoi_nav(self) -> str:
        """Build AOI navigation items."""
        lines = []
        for aoi in self.controller.add_on_instructions:
            name = self._id(aoi.name)          # HTML-safe; may be bilingual span
            aoi_id = html.escape(aoi.name)      # raw identifier for section IDs / JS args
            lines.append(f'                    <li>')
            lines.append(f'                        <a href="#aoi-{aoi_id}" '
                        f'onclick="showSection(\'aoi-{aoi_id}\')">'
                        f'<svg class="icon icon-sm"><use href="#mdi-wrench"></use></svg> {name}</a>')
            lines.append(f'                    </li>')
        return '\n'.join(lines)
    
    def _build_equipment_nav(self) -> str:
        """Build equipment/other projects navigation."""
        lines = []
        # Add link to index at the top
        lines.append('                        <li>')
        lines.append('                            <a href='
                     '"../../../index.html">')
        lines.append('                                '
                     '<svg class="icon icon-sm">'
                     '<use href="#mdi-clipboard"></use>'
                     '</svg> All Projects')
        lines.append('                            </a>')
        lines.append('                        </li>')
        for name, url in sorted(self.navigation_links.items()):
            escaped_url = html.escape(url)
            escaped_name = html.escape(name)
            lines.append('                        <li>')
            lines.append('                            '
                         f'<a href="{escaped_url}">')
            lines.append('                                '
                         f'<svg class="icon icon-sm">'
                         f'<use href="#mdi-folder"></use>'
                         f'</svg> {escaped_name}')
            lines.append('                            </a>')
            lines.append('                        </li>')
        return '\n'.join(lines) if self.navigation_links else ''
    
    def _build_scope_options(self) -> str:
        """Build scope filter options."""
        lines = []
        for program in self.controller.programs:
            lines.append(f'                        <option value="{html.escape(program.name)}">'
                        f'{html.escape(program.name)}</option>')
        return '\n'.join(lines)
    
    def _build_tag_rows(self) -> str:
        """Build tag table rows."""
        lines = []
        for tag in self.controller.controller_tags:
            usage_count = len(tag.usages)
            usage_html = (f'<span class="usage-badge" onclick="showUsages(\'{html.escape(tag.name)}\')">'
                         f'{usage_count}</span>') if usage_count > 0 else '-'
            
            lines.append(f'''                            <tr>
                                <td><span class="tag-link" onclick="showUsages('{html.escape(tag.name)}')">{self._id(tag.name)}</span></td>
                                <td>{html.escape(tag.data_type)}</td>
                                <td>{html.escape(tag.scope)}</td>
                                <td>{self._t(tag.description)}</td>
                                <td>{usage_html}</td>
                            </tr>''')

        # Also add program-scoped tags
        for program in self.controller.programs:
            for tag in program.local_tags:
                usage_count = len(tag.usages)
                usage_html = (f'<span class="usage-badge" onclick="showUsages(\'{html.escape(tag.name)}\')">'
                             f'{usage_count}</span>') if usage_count > 0 else '-'

                lines.append(f'''                            <tr>
                                <td><span class="tag-link" onclick="showUsages('{html.escape(tag.name)}')">{self._id(tag.name)}</span></td>
                                <td>{html.escape(tag.data_type)}</td>
                                <td>{html.escape(program.name)}</td>
                                <td>{self._t(tag.description)}</td>
                                <td>{usage_html}</td>
                            </tr>''')

        return '\n'.join(lines)

    def _build_datatype_cards(self) -> str:
        """Build data type cards."""
        lines = []
        for dt in self.controller.data_types:
            members_html = ''
            for member in dt.members[:10]:  # Show first 10 members
                members_html += f'''<div class="member">
                    <span>{html.escape(member.name)}</span>
                    <span class="member-type">{html.escape(member.data_type)}</span>
                </div>'''

            if len(dt.members) > 10:
                members_html += f'<div class="member"><em>...and {len(dt.members) - 10} more</em></div>'

            lines.append(f'''                    <div class="card">
                        <h4>{html.escape(dt.name)}</h4>
                        <p>{self._t(dt.description)}</p>
                        <div class="member-list">
                            {members_html}
                        </div>
                    </div>''')
        return '\n'.join(lines)
    
    def _get_controller_ips(self) -> list[str]:
        """Collect up to two PLC port IP addresses with Front/Back labels."""
        ips: list[str] = []

        if self.controller.comm_path:
            match = re.search(r'(\d+\.\d+\.\d+\.\d+)', self.controller.comm_path)
            if match:
                ips.append(f"A1 (Front): {match.group(1)}")

        port_ips: dict[str, set[str]] = {}
        controller_aliases = {self.controller.name.lower(), 'local', ''}
        for module in self.controller.modules:
            parent = (module.parent_module or '').strip().lower()
            if parent == module.name.lower():
                parent = ''
            if parent not in controller_aliases:
                continue
            port_id = (module.parent_port or '').strip()
            if not port_id:
                continue
            for port in module.ports:
                if port.port_type == 'Ethernet' and '.' in port.address:
                    port_ips.setdefault(port_id, set()).add(port.address)

        port_labels = {'3': 'A1 (Front)', '4': 'A2 (Back)'}
        for port_id in sorted(port_ips.keys()):
            if len(ips) >= 2:
                break
            candidate = sorted(port_ips[port_id])[0]
            label = port_labels.get(port_id, f"Port {port_id}")
            entry = f"{label}: {candidate}"
            if entry not in ips:
                ips.append(entry)

        return ips[:2]

    def _classify_device_type(self, module: Module) -> str:
        """Classify device type for styling and icons."""
        cat = (module.catalog_number or '').upper()
        name = (module.name or '').upper()

        # HMI / Display
        if 'PANELVIEW' in name or 'PANELVIEW' in cat or name.startswith('PV'):
            return 'hmi'
        
        # Servo / Motion
        if any(x in name or x in cat for x in ['SERVO', 'KINCO', 'STEPPER']):
            return 'servo'
        
        # Network adapters
        if any(x in cat for x in ['AENT', 'EN2T', 'ENBT', '5069-EN']) or ('ENET' in cat and 'EENET' not in cat):
            return 'adapter'
        
        # Drives
        if 'POWERFLEX' in cat or name.startswith('PF') or 'EENET' in cat:
            return 'drive'
        
        # Safety modules
        if 'SAFETY' in name or 'GUARD' in cat or 'SAFE' in cat:
            return 'safety'
        
        # Network switches
        if 'SWITCH' in name:
            return 'switch'
        
        # Input modules
        if '-IB' in cat or 'INPUT' in name:
            return 'input'
        
        # Output modules
        if '-OB' in cat or 'OUTPUT' in name:
            return 'output'
        
        # Analog modules
        if any(x in cat for x in ['-IE', '-IF', '-OE', '-OF']) or 'ANALOG' in name or 'RTD' in cat or 'THERMO' in cat:
            return 'analog'
        
        # Generic I/O
        if any(cat.startswith(x) for x in ['1734', '1769', '5069']):
            return 'io'
        
        return 'device'

    def _build_network_tree_data(self) -> Optional[dict]:
        """Build hierarchical data for the interactive network diagram."""
        if not self.controller.modules:
            return None

        controller_node = {
            'id': '__CONTROLLER__',
            'name': self._idj(self.controller.name or 'Controller'),
            'catalog': self.controller.processor_type,
            'device_type': 'controller',
            'ips': self._get_controller_ips(),
            'children': [],
        }

        nodes: dict[str, dict] = {controller_node['id']: controller_node}
        links: list[tuple[str, str, str]] = []

        ctrl_name = (self.controller.name or '').lower()
        for idx, module in enumerate(self.controller.modules):
            raw = (module.name or '').strip()
            # The "Local" module is the controller's own backplane - it is already
            # represented by the controller node, so don't duplicate it.
            if raw.lower() == 'local' or (not raw and module.catalog_number == self.controller.processor_type):
                continue

            ips = [
                port.address
                for port in module.ports
                if port.port_type == 'Ethernet' and '.' in port.address
            ]

            # Local I/O modules often carry no Name in the L5X (referenced by slot).
            # Give each a unique id + a readable label so they don't collide.
            node_id = raw or f"__mod{idx}__"
            display = raw or f"{module.catalog_number or 'Module'}" + (f" (slot {module.slot})" if module.slot else "")

            nodes[node_id] = {
                'id': node_id,
                'name': self._idj(display),
                'catalog': module.catalog_number,
                'device_type': self._classify_device_type(module),
                'ips': ips,
                'children': [],
            }

            parent_name = (module.parent_module or '').strip()
            if raw and parent_name.lower() == raw.lower():
                parent_name = ''
            parent_key = ('__CONTROLLER__'
                          if parent_name.lower() in ('', 'local', ctrl_name)
                          else parent_name)
            links.append((parent_key, node_id, module.parent_port or module.slot or ''))

        for parent_key, child_key, edge_label in links:
            parent_node = nodes.get(parent_key)
            if not parent_node:
                parent_node = {
                    'id': parent_key,
                    'name': self._idj(parent_key),
                    'catalog': '',
                    'device_type': 'group',
                    'ips': [],
                    'children': [],
                }
                nodes[parent_key] = parent_node

            child_node = nodes.get(child_key)
            if not child_node:
                continue

            child_node['edge_label'] = self._idj(edge_label)
            parent_node.setdefault('children', []).append(child_node)

        return controller_node if controller_node.get('children') else None

    def _build_network_diagram_section(self) -> str:
        """Build the network diagram section for the overview."""
        tree = self._build_network_tree_data()
        self.network_tree_data = tree

        if not tree:
            return '''
                <h3 style="margin-top: 2rem;">Network Diagram</h3>
                <div class="network-diagram-container">
                    <p class="network-note">Network diagram unavailable because the L5X export did not include Ethernet-connected modules.</p>
                </div>'''

        return '''
                <h3 style="margin-top: 2rem;">Network Diagram</h3>
                <div class="network-diagram-container">
                    <div class="network-tree-controls">
                        <button class="net-btn" id="net-expand-all">Expand all</button>
                        <button class="net-btn" id="net-collapse-all">Collapse all</button>
                    </div>
                    <div id="network-diagram" class="network-diagram"></div>
                    <p class="network-note">Click any node to expand or collapse. Badges show subdevice counts; colors indicate device type.</p>
                </div>'''

    def _build_ethernet_devices_section(self) -> str:
        """Build section showing Ethernet devices with IP addresses."""
        # Collect modules with Ethernet ports
        ethernet_devices = []
        for module in self.controller.modules:
            for port in module.ports:
                # Look for Ethernet ports with IP-like addresses
                if port.port_type == 'Ethernet' and '.' in port.address:
                    ethernet_devices.append({
                        'name': module.name,
                        'catalog': module.catalog_number,
                        'ip': port.address,
                        'port_id': port.port_id,
                    })
        
        if not ethernet_devices:
            return ''
        
        rows = []
        for dev in ethernet_devices:
            # L5X export does not include subnet/gateway/DHCP state for ports; show N/A when unavailable
            rows.append(f'''                            <tr>
                                <td>{html.escape(dev['name'])}</td>
                                <td>{html.escape(dev['catalog'])}</td>
                                <td><code>{html.escape(dev['ip'])}</code></td>
                                <td>N/A</td>
                                <td>N/A</td>
                                <td>N/A</td>
                                <td>Port {html.escape(dev['port_id'])}</td>
                            </tr>''')
        
        return f'''
                <h3 style="margin-top: 2rem;">Ethernet Devices</h3>
                <div class="table-container">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Device</th>
                                <th>Catalog Number</th>
                                <th>IP Address</th>
                                <th>Subnet Mask</th>
                                <th>Gateway</th>
                                <th>DHCP/Static</th>
                                <th>Port</th>
                            </tr>
                        </thead>
                        <tbody>
{''.join(rows)}
                        </tbody>
                    </table>
                    <p class="network-note">Subnet, gateway, and DHCP details are not included in L5X exports; values are shown as N/A.</p>
                </div>'''
    
    def _extract_ip_from_controller(self) -> str:
        """Extract IP address from controller's modules or comm_path."""
        ips = self._get_controller_ips()
        if ips:
            if len(ips) == 1:
                return f'IP: {html.escape(ips[0])}'
            joined = ' | '.join(html.escape(ip) for ip in ips)
            return f'IPs: {joined}'
        
        return 'IP: Not Configured'
    
    def _build_module_rows(self) -> str:
        """Build module table rows with links to I/O points."""
        lines = []
        for module in self.controller.modules:
            # Find IP address from Ethernet ports
            ip_address = ''
            for port in module.ports:
                if port.port_type == 'Ethernet' and '.' in port.address:
                    ip_address = port.address
                    break

            parent_info = ''
            if module.parent_module:
                parent_info = f"{module.parent_module}:{module.parent_port}"

            # Count I/O points
            io_count = len(module.io_points)
            io_link = ''
            if io_count > 0:
                mod_id = html.escape(module.name)
                io_link = (
                    f'<a href="#io-module-{mod_id}" '
                    f'onclick="showSection(\'io-points\'); '
                    f'setTimeout(() => document.getElementById'
                    f'(\'io-module-{mod_id}\')?.scrollIntoView'
                    f'({{behavior:\'smooth\'}}), 100)">'
                    f'{io_count} points</a>'
                )
            else:
                io_link = '-'

            lines.append(f'''                            <tr>
                                <td>{html.escape(module.name)}</td>
                                <td>{html.escape(module.catalog_number)}</td>
                                <td>{html.escape(module.slot)}</td>
                                <td>{html.escape(parent_info)}</td>
                                <td><code>{html.escape(ip_address)}</code></td>
                                <td>{io_link}</td>
                            </tr>''')
        return '\n'.join(lines)

    def _clean_comment(self, comment: str) -> str:
        """Clean rung comments by removing repeated characters."""
        if not comment:
            return ""
        
        # Remove lines that are just repeated characters (e.g., //////)
        lines = comment.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.strip()
            # Check if line is mostly repeated single character
            if stripped and len(stripped) > 3:
                # Check if same char repeated
                first_char = stripped[0]
                if all(c == first_char for c in stripped):
                    continue  # Skip this line
                # Check for patterns like "====" or "----" or "////"
                if re.match(r'^(.)\1{3,}$', stripped):
                    continue
            cleaned.append(line)
        
        result = '\n'.join(cleaned).strip()
        # Remove leading/trailing repeated char lines
        result = re.sub(r'^[=\-/\\*#]{4,}\n?', '', result)
        result = re.sub(r'\n?[=\-/\\*#]{4,}$', '', result)
        return result.strip()

    def _build_io_usage_map(self) -> dict:
        """Build a map of I/O tag references to their usage info.
        
        Rockwell I/O references can be in multiple formats:
        - ParentModule:Slot:I.Point (e.g., HEAT_ZONE_1:1:I.00)
        - ParentModule:Slot:I.ChXData (e.g., HEAT_ZONE_1:11:I.Ch0Data)
        - ModuleName:I.Data.Point (e.g., LOCAL_INPUT:I.Data.0)
        
        Also captures rung comments and logic for building I/O descriptions.
        """
        usage_map = {}  # tag_ref -> {'used': bool, 'mappings': [], 'comments': [], 'logic_desc': str}

        # Pattern to find I/O references in rung text
        # Matches: Module:Slot:I.Point or Module:I.Point
        io_pattern = re.compile(
            r'([A-Za-z_][A-Za-z0-9_]*)(?::(\d+))?:(I|O)\.([A-Za-z0-9_\[\].]+)'
        )
        
        # Pattern to extract instruction and operands
        instr_pattern = re.compile(r'([A-Z_][A-Z0-9_]*)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)', re.IGNORECASE)

        for program in self.controller.programs:
            for routine in program.routines:
                for rung in routine.rungs:
                    text = rung.text or ''
                    comment = self._clean_comment(rung.comment or '')
                    
                    for m in io_pattern.finditer(text):
                        mod_or_parent, slot, io_type, point = m.groups()
                        # Build tag reference matching parser format
                        if slot:
                            tag_ref = f"{mod_or_parent}:{slot}:{io_type}.{point}"
                        else:
                            tag_ref = f"{mod_or_parent}:{io_type}.{point}"
                        
                        if tag_ref not in usage_map:
                            usage_map[tag_ref] = {
                                'used': True,
                                'mappings': [],
                                'comments': [],
                                'logic_desc': '',
                                'mapped_tags': [],
                                'io_direction': io_type  # 'I' or 'O'
                            }
                        usage_map[tag_ref]['mappings'].append({
                            'program': program.name,
                            'routine': routine.name,
                            'rung': rung.number
                        })
                        # Capture comment for description building
                        if comment and comment not in usage_map[tag_ref]['comments']:
                            usage_map[tag_ref]['comments'].append(comment)
                        
                        # Try to build logic description
                        if not usage_map[tag_ref]['logic_desc']:
                            logic_desc = self._build_logic_description(text, tag_ref, io_type)
                            if logic_desc:
                                usage_map[tag_ref]['logic_desc'] = logic_desc

        # Also check alias tags
        all_tags = list(self.controller.controller_tags)
        for prog in self.controller.programs:
            all_tags.extend(prog.local_tags)
        
        # Build a tag description lookup
        tag_descriptions = {t.name: t.description for t in all_tags if t.description}

        for tag in all_tags:
            if tag.alias_for and (':I' in tag.alias_for or ':O' in tag.alias_for):
                if tag.alias_for not in usage_map:
                    usage_map[tag.alias_for] = {
                        'used': True, 'mappings': [], 'comments': [],
                        'logic_desc': '', 'mapped_tags': [], 'io_direction': 'I' if ':I' in tag.alias_for else 'O'
                    }
                # Also mark the alias name as a mapping
                usage_map[tag.alias_for]['alias'] = tag.name
                usage_map[tag.alias_for]['alias_desc'] = tag.description
        
        # Store tag descriptions for later use in logic description fallback
        self._tag_descriptions = tag_descriptions

        return usage_map
    
    def _build_logic_description(self, rung_text: str, tag_ref: str, io_type: str) -> str:
        """Build a human-readable description from rung logic.
        
        For inputs: "Read by <output_tag>" or "Enables <output_description>"
        For outputs: "Set by <input conditions>"
        """
        # Pattern to extract all instructions
        instr_pattern = re.compile(r'([A-Z_][A-Z0-9_]*)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)', re.IGNORECASE)
        
        instructions = []
        for m in instr_pattern.finditer(rung_text):
            instr_name = m.group(1).upper()
            operands = [op.strip() for op in m.group(2).split(',') if op.strip()]
            instructions.append((instr_name, operands))
        
        if not instructions:
            return ''
        
        # Separate inputs (conditions) from outputs (actions)
        condition_instrs = ['XIC', 'XIO', 'EQU', 'NEQ', 'LES', 'LEQ', 'GRT', 'GEQ', 'LIM', 'ONS', 'OSR', 'OSF']
        output_instrs = ['OTE', 'OTL', 'OTU', 'TON', 'TOF', 'RTO', 'CTU', 'CTD', 'MOV', 'ADD', 'SUB', 'MUL', 'DIV']
        
        conditions = [(name, ops) for name, ops in instructions if name in condition_instrs]
        outputs = [(name, ops) for name, ops in instructions if name in output_instrs]
        
        # Check if this tag_ref is in the conditions or outputs
        tag_ref_escaped = tag_ref.replace('.', r'\.').replace('[', r'\[').replace(']', r'\]')
        tag_ref_pattern = re.compile(tag_ref_escaped, re.IGNORECASE)
        
        if io_type == 'I':
            # Input point - what does it control?
            output_tags = []
            for name, ops in outputs:
                for op in ops:
                    if tag_ref_pattern.search(op):
                        output_tags.append((name, op))

            if not output_tags:
                return ''
            if len(output_tags) == 1:
                return f"→ {output_tags[0][1]}"

            tags = [t[1] for t in output_tags[:3]]
            suffix = '...' if len(output_tags) > 3 else ''
            return f"→ {', '.join(tags)}{suffix}"

        else:  # io_type == 'O'
            # Output point - what conditions set it?
            condition_tags = []
            for name, ops in conditions:
                for op in ops:
                    condition_tags.append((name, op))

            if not condition_tags:
                return ''
            if len(condition_tags) == 1:
                cond_type, cond_tag = condition_tags[0]
                return f"← {cond_type} {cond_tag}"

            tags = [f"{n} {t}" for n, t in condition_tags[:3]]
            suffix = '...' if len(condition_tags) > 3 else ''
            return f"← {' AND '.join(tags)}{suffix}"
        
        return ''

    def _build_io_points_content(self) -> str:
        """Build grouped I/O points content with module headers."""
        lines = []
        usage_map = self._build_io_usage_map()

        # Group modules by parent (for remote I/O structure)
        io_modules = [m for m in self.controller.modules if m.io_points]

        if not io_modules:
            return '''<div class="info-card">
                <p>No I/O modules with enumerable points found.</p>
            </div>'''

        for module in io_modules:
            mod_id = html.escape(module.name)
            catalog = html.escape(module.catalog_number)
            slot = html.escape(module.slot or '-')
            parent = html.escape(module.parent_module or '-')

            # Count used/spare - a point is "used" if referenced in logic OR has a description
            used_count = 0
            spare_count = 0
            for pt in module.io_points:
                has_usage = usage_map.get(pt.tag_reference, {}).get('used')
                has_desc = bool(pt.description)
                if has_usage or has_desc:
                    used_count += 1
                else:
                    spare_count += 1

            lines.append(f'''
            <div id="io-module-{mod_id}" class="io-module-header">
                <h4>{mod_id}</h4>
                <span class="module-info">{catalog} | Slot {slot} | Parent: {parent} | Used: {used_count} | Spare: {spare_count}</span>
            </div>
            <div class="table-container" style="border-radius: 0 0 8px 8px; margin-bottom: 20px;">
                <table class="data-table io-points-table">
                    <thead>
                        <tr>
                            <th>Module</th>
                            <th>Point</th>
                            <th>Type</th>
                            <th>Tag / Mapping</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>''')

            for pt in module.io_points:
                tag_ref = pt.tag_reference
                type_class = 'input' if pt.point_type == 'Input' else 'output'
                usage = usage_map.get(tag_ref, {})
                is_used = usage.get('used', False)

                # Build description - try multiple sources in order of preference
                # Prefer alias description if mapped 1:1
                desc = ''
                if usage.get('alias') and usage.get('alias_desc'):
                    desc = usage['alias_desc']
                
                if not desc:
                    desc = pt.description
                
                if not desc and usage.get('alias_desc'):
                    desc = usage['alias_desc']
                    
                if not desc and usage.get('comments'):
                    # Build from rung comments
                    comments = usage['comments']
                    if len(comments) == 1:
                        desc = comments[0][:60]
                    else:
                        # Use first meaningful comment
                        desc = comments[0][:40]
                if not desc and usage.get('logic_desc'):
                    # Build from logic analysis
                    desc = usage['logic_desc']
                # NOTE: desc stays as raw text here — translated at emit time via _t()

                # A point is spare only if not used AND has no description
                is_spare = not is_used and not desc

                # Build tag display and onclick handler
                onclick_attr = ''
                if is_spare:
                    tag_display = '<span class="io-spare-badge">SPARE</span>'
                elif usage.get('alias'):
                    alias = html.escape(usage['alias'])
                    onclick_attr = f'onclick="showUsages(\'{alias}\')"'
                    tag_display = (
                        f'<span class="io-point-link" {onclick_attr}>'
                        f'{alias}</span>'
                    )
                else:
                    # Show the raw tag reference as clickable
                    onclick_attr = (
                        f'onclick="showIOPointXref(\'{html.escape(tag_ref)}\', '
                        f'\'{html.escape(module.name)}\', {pt.point_number}, '
                        f'\'{pt.point_type}\')"'
                    )
                    tag_display = (
                        f'<span class="io-point-link" {onclick_attr}>'
                        f'<code>{html.escape(tag_ref)}</code></span>'
                    )

                spare_attr = 'true' if is_spare else 'false'

                # Make description clickable if it exists and we have a handler
                # _t() returns already-escaped HTML (span or plain escaped text)
                desc_html = self._t(desc) if desc else ''
                if desc and onclick_attr:
                    desc_html = f'<span class="clickable-desc" {onclick_attr} style="cursor:pointer; border-bottom:1px dotted #aaa;">{desc_html}</span>'

                lines.append(f'''
                        <tr data-io-type="{pt.point_type}" data-spare="{spare_attr}">
                            <td>{html.escape(module.name)}</td>
                            <td>{html.escape(pt.operand)}</td>
                            <td><span class="io-type-badge {type_class}">{pt.point_type}</span></td>
                            <td>{tag_display}</td>
                            <td>{desc_html}</td>
                        </tr>''')

            lines.append('''
                    </tbody>
                </table>
            </div>''')

        return '\n'.join(lines)

    def _build_io_points_rows(self) -> str:
        """Legacy method - kept for compatibility."""
        return ''

    def _build_alarm_rows(self) -> str:
        """Build alarm summary rows by scanning for alarm-related tags and logic."""
        lines = []
        
        # Patterns that typically indicate alarm/fault logic
        alarm_patterns = [
            'alarm', 'alm', 'fault', 'flt', 'error', 'err', 'warning', 'warn',
            'estop', 'e-stop', 'emergency', 'trip', 'fail', 'failure', 'alert'
        ]
        
        alarm_tags = []
        
        # Scan controller tags
        for tag in self.controller.controller_tags:
            tag_lower = tag.name.lower()
            desc_lower = (tag.description or '').lower()
            
            alarm_type = None
            for pattern in alarm_patterns:
                if pattern in tag_lower or pattern in desc_lower:
                    # Determine alarm type based on pattern
                    if 'fault' in pattern or 'flt' in pattern:
                        alarm_type = 'Fault'
                    elif 'estop' in pattern or 'e-stop' in pattern or 'emergency' in pattern:
                        alarm_type = 'E-Stop'
                    elif 'warning' in pattern or 'warn' in pattern:
                        alarm_type = 'Warning'
                    else:
                        alarm_type = 'Alarm'
                    break
            
            if alarm_type:
                # Find where this tag is used
                locations = []
                for usage in tag.usages[:3]:  # Show first 3 usages
                    locations.append(f"{usage.program} → {usage.routine}")
                location_str = '; '.join(locations) if locations else 'Not used'
                
                alarm_tags.append({
                    'name': tag.name,
                    'type': alarm_type,
                    'description': tag.description,  # raw; translated at emit time via _t()
                    'location': location_str
                })

        # Also scan program tags
        for program in self.controller.programs:
            for tag in program.local_tags:
                tag_lower = tag.name.lower()
                desc_lower = (tag.description or '').lower()

                alarm_type = None
                for pattern in alarm_patterns:
                    if pattern in tag_lower or pattern in desc_lower:
                        if 'fault' in pattern or 'flt' in pattern:
                            alarm_type = 'Fault'
                        elif 'estop' in pattern or 'e-stop' in pattern or 'emergency' in pattern:
                            alarm_type = 'E-Stop'
                        elif 'warning' in pattern or 'warn' in pattern:
                            alarm_type = 'Warning'
                        else:
                            alarm_type = 'Alarm'
                        break

                if alarm_type:
                    locations = []
                    for usage in tag.usages[:3]:
                        locations.append(f"{usage.program} → {usage.routine}")
                    location_str = '; '.join(locations) if locations else program.name

                    alarm_tags.append({
                        'name': tag.name,
                        'type': alarm_type,
                        'description': tag.description,  # raw; translated at emit time via _t()
                        'location': location_str
                    })

        # Sort by type then name
        type_order = {'E-Stop': 0, 'Fault': 1, 'Alarm': 2, 'Warning': 3}
        alarm_tags.sort(key=lambda x: (type_order.get(x['type'], 99), x['name']))

        for alarm in alarm_tags:
            type_class = alarm['type'].lower().replace('-', '')
            lines.append(f'''                            <tr>
                                <td><span class="tag-link" onclick="showUsages('{html.escape(alarm['name'])}')">{html.escape(alarm['name'])}</span></td>
                                <td><span class="alarm-type-badge {type_class}">{html.escape(alarm['type'])}</span></td>
                                <td>{self._t(alarm['description'])}</td>
                                <td>{html.escape(alarm['location'])}</td>
                            </tr>''')
        
        if not lines:
            lines.append('''                            <tr>
                                <td colspan="4" style="text-align: center; color: var(--text-secondary);">
                                    No alarm-related tags found. Alarms are detected by scanning for tags containing: alarm, fault, error, warning, estop, etc.
                                </td>
                            </tr>''')
        
        return '\n'.join(lines)
    
    def _build_device_section(self) -> str:
        """Build the devices section."""
        if not hasattr(self, 'devices') or not self.devices:
            return '''
            <section id="devices" class="section">
                <h2><svg class="icon icon-lg"><use href="#mdi-engine"></use></svg> Devices</h2>
                <p>No devices (Servos/VFDs) detected.</p>
            </section>
            '''
            
        device_cards = []
        for device in self.devices:
            # Build Setpoints Table
            setpoints_html = ""
            if device.setpoints:
                rows = []
                for sp in device.setpoints:
                    rows.append(f'''
                        <tr>
                            <td>{html.escape(sp.name)}</td>
                            <td><code>{html.escape(sp.value)}</code></td>
                            <td>{html.escape(sp.description)}</td>
                        </tr>
                    ''')
                setpoints_html = f'''
                    <div class="device-subsection">
                        <h5>Setpoints</h5>
                        <table class="data-table">
                            <thead><tr><th>Parameter</th><th>Value</th><th>Description</th></tr></thead>
                            <tbody>{''.join(rows)}</tbody>
                        </table>
                    </div>
                '''
            
            # Build Controls List
            controls_html = ""
            if device.controls:
                items = []
                for ctrl in device.controls:
                    # Construct rung key for inline rendering
                    rung_key = f"{ctrl.program}_{ctrl.routine}_{ctrl.rung}"
                    
                    # Construct navigation IDs
                    section_id = f"program-{html.escape(ctrl.program)}"
                    rung_id = f"rung-{html.escape(ctrl.program)}-{html.escape(ctrl.routine)}-{ctrl.rung}"
                    
                    items.append(f'''
                        <div class="control-item">
                            <div class="control-header">
                                <span class="control-type">{html.escape(ctrl.type)}</span>
                                <span class="control-location">
                                    {html.escape(ctrl.program)} &rarr; {html.escape(ctrl.routine)} : Rung {ctrl.rung}
                                    <button class="view-ladder-btn" onclick="navigateToRung('{section_id}', '{rung_id}')" title="Go to Logic">
                                        <svg class="icon"><use href="#mdi-arrow-expand"></use></svg>
                                    </button>
                                </span>
                            </div>
                            <div class="ladder-inline-container" data-rung-key="{rung_key}">
                                <div class="ladder-loading">Loading logic...</div>
                            </div>
                        </div>
                    ''')
                controls_html = f'''
                    <div class="device-subsection">
                        <h5>Controls</h5>
                        <div class="controls-list">
                            {''.join(items)}
                        </div>
                    </div>
                '''
            
            device_cards.append(f'''
                <details class="card device-card">
                    <summary class="device-header">
                        <div class="device-title">
                            <h4><svg class="icon"><use href="#mdi-engine"></use></svg> {html.escape(device.name)}</h4>
                            <span class="device-type">{html.escape(device.device_type)}</span>
                        </div>
                        <p class="device-description-summary">{html.escape(device.description)}</p>
                    </summary>
                    <div class="device-content">
                        <p class="device-description-full">{html.escape(device.description)}</p>
                        {setpoints_html}
                        {controls_html}
                    </div>
                </details>
            ''')
            
        return f'''
            <section id="devices" class="section">
                <h2><svg class="icon icon-lg"><use href="#mdi-engine"></use></svg> Devices</h2>
                <div class="device-list">
                    {''.join(device_cards)}
                </div>
            </section>
        '''

    def _build_program_sections(self) -> str:
        """Build program sections: one index page per program plus one page per
        routine. Per-routine pages make rung navigation unambiguous (each rung id
        is unique to a single visible page) and keep long programs scannable."""
        sections = []
        for program in self.controller.programs:
            name = self._id(program.name)           # HTML; may be bilingual span
            prog_id = html.escape(program.name)     # raw identifier for section IDs / JS args

            # Program index — a dense, clickable list of the program's routines.
            index_items = []
            for routine in program.routines:
                rname = self._id(routine.name)          # HTML; may be bilingual span
                rname_plain = html.escape(routine.name) # raw, for title attr (no HTML)
                sec = f"routine-{prog_id}-{html.escape(routine.name)}"
                is_main = (routine.name == program.main_routine)
                main_badge = '<span class="rt-badge">MAIN</span>' if is_main else ''
                rung_n = len(routine.rungs)
                index_items.append(
                    f'<li class="rt-index-item" onclick="showSection(\'{sec}\')" '
                    f'title="Open {rname_plain}">'
                    f'<svg class="icon icon-sm"><use href="#mdi-clipboard"></use></svg>'
                    f'<span class="rt-name">{rname}</span>{main_badge}'
                    f'<span class="rt-meta">{html.escape(routine.routine_type)}'
                    f' &middot; {rung_n} rung{"s" if rung_n != 1 else ""}</span></li>'
                )
            main_disp = self._id(program.main_routine) if program.main_routine else ''
            main_html = f'Main routine: <strong>{main_disp}</strong> &middot; ' if main_disp else ''
            sections.append(f'''
            <section id="program-{prog_id}" class="section">
                <h2><svg class="icon icon-lg"><use href="#mdi-folder"></use></svg> {name}</h2>
                <p class="program-sub">{main_html}{len(program.routines)} routines</p>
                <ul class="rt-index">{''.join(index_items)}</ul>
            </section>''')

            # One full page per routine.
            for routine in program.routines:
                sections.append(self._build_routine_page(program, routine))

        return '\n'.join(sections)

    def _build_routine_page(self, program: Program, routine: Routine) -> str:
        """Render a single routine as its own navigable page/section."""
        prog_id = html.escape(program.name)                # raw — section ID / JS arg
        sec_id = f"routine-{prog_id}-{html.escape(routine.name)}"
        disp_routine = self._id(routine.name)              # HTML; may be bilingual span
        disp_program = self._id(program.name)              # HTML; may be bilingual span
        is_main = (routine.name == program.main_routine)
        main_badge = '<span class="rt-badge">MAIN</span>' if is_main else ''
        inner = self._build_routine_inner(program.name, routine, disp_routine)
        return f'''
            <section id="{sec_id}" class="section routine-page"
                     data-program="{html.escape(program.name)}"
                     data-routine="{html.escape(routine.name)}"
                     data-program-section="program-{prog_id}">
                <h2><svg class="icon icon-lg"><use href="#mdi-clipboard-outline"></use></svg> {disp_routine}{main_badge}</h2>
                <p class="program-sub"><a class="crumb" onclick="showSection('program-{prog_id}')">{disp_program}</a> &middot; {html.escape(routine.routine_type)} &middot; {len(routine.rungs)} rungs</p>
                {inner}
            </section>'''

    def _build_routine_inner(self, program_name: str, routine: Routine, display_name: str) -> str:
        """The body of a routine page: ST code block, or the ladder listing."""
        if routine.routine_type == 'ST':
            st_text = routine.rungs[0].text if routine.rungs else ''
            placeholder = ('<em style="color: var(--text-secondary);">No structured text content</em>'
                           if not st_text else '')
            desc = self._t(routine.description) if routine.description else ''
            desc_html = f'<div class="rung-comment">{desc}</div>' if desc else ''
            return f'''
                <div class="routine-listing">
                    {desc_html}
                    {placeholder}
                    <pre class="rung-text">{html.escape(st_text)}</pre>
                </div>'''
        rungs_html = self._build_rungs(program_name, routine)
        no_logic = ('' if len(routine.rungs) > 0
                    else '<em style="color: var(--text-secondary);">No logic in this routine</em>')
        return f'''
                <div class="routine-listing" data-routine-listing="{html.escape(routine.name)}">
                    {no_logic}
                    {rungs_html}
                </div>'''
    
    def _build_aoi_sections(self) -> str:
        """Build AOI detail sections."""
        sections = []
        for aoi in self.controller.add_on_instructions:
            routines_html = self._build_aoi_routine_content(aoi)
            name = self._id(aoi.name)          # HTML-safe; may be bilingual span
            aoi_id = html.escape(aoi.name)      # raw identifier for section IDs

            sections.append(f'''
            <section id="aoi-{aoi_id}" class="section">
                <h2><svg class="icon icon-lg"><use href="#mdi-wrench"></use></svg> {name}</h2>
                <p><strong>Revision:</strong> {html.escape(aoi.revision)}</p>
                <p><strong>Vendor:</strong> {html.escape(aoi.vendor)}</p>
                <p>{self._t(aoi.description)}</p>
                {routines_html}
            </section>''')
        
        return '\n'.join(sections)
    
    def _build_aoi_routine_content(self, aoi) -> str:
        """Build routine content for an AOI."""
        content = []
        for routine in aoi.routines:
            rungs_html = self._build_rungs(f"AOI_{aoi.name}", routine)

            content.append(f'''
                <div class="routine-container">
                    <div class="routine-header">
                        <h4>{self._id(routine.name)}</h4>
                        <span>{routine.routine_type} &middot; {len(routine.rungs)} rungs</span>
                    </div>
                    <div class="routine-body">
                        {rungs_html}
                    </div>
                </div>''')
        
        return '\n'.join(content)
    
    def _build_rungs(self, program_name: str, routine: Routine) -> str:
        """Build rung content for a routine."""
        rungs = []
        for rung in routine.rungs:
            # Build rung comment (larger, separate from number).
            # Filter on raw text first (language-independent); translate at emit time.
            comment_text = rung.comment if rung.comment else ''
            if comment_text:
                # Drop long separator lines (e.g., ========================)
                filtered_lines = [
                    line for line in comment_text.splitlines()
                    if not re.fullmatch(r"=+", line.strip())
                ]
                comment_text = "\n".join(filtered_lines).strip()
            comment_html = (
                f'<div class="rung-comment">{self._t(comment_text)}</div>'
                if comment_text else ''
            )
            
            rung_key = f"{program_name}_{routine.name}_{rung.number}"
            rung_id = f"rung-{program_name}-{routine.name}-{rung.number}"
            
            rungs.append(f'''
                        <div class="rung" id="{html.escape(rung_id)}">
                            <div class="rung-number-col">{rung.number}</div>
                            <div class="rung-content">
                                <div class="rung-icon-buttons">
                                    <button class="rung-icon-btn expand-btn" onclick="showLadder('{html.escape(program_name)}', '{html.escape(routine.name)}', {rung.number})" title="Expand diagram">
                                        <svg class="icon"><use href="#mdi-arrow-expand"></use></svg>
                                    </button>
                                    <button class="rung-icon-btn text-btn" onclick="toggleRungText(this)" title="Show/hide text">
                                        <svg class="icon"><use href="#mdi-eye"></use></svg>
                                    </button>
                                </div>
                                {comment_html}
                                <div class="ladder-inline-container" data-rung-key="{html.escape(rung_key)}">
                                        <div class="ladder-loading">Loading diagram...</div>
                                    </div>
                                    <div class="rung-tag-desc" aria-label="Tag descriptions"></div>
                                    <pre class="rung-text hidden">{html.escape(rung.text)}</pre>
                            </div>
                        </div>''')
        
        return '\n'.join(rungs)


def generate_documentation(
    controller: Controller,
    output_path: Path,
    translate: bool = False,
    navigation_links: Optional[dict] = None,
    inline_assets: bool = False,
    bilingual: bool = False,
    use_online: bool = False,
) -> str:
    """
    Generate HTML documentation for a controller.

    Args:
        controller: Parsed L5X controller
        output_path: Path to write HTML file
        translate: Kept for backward compatibility (deprecated; use bilingual=True).
        navigation_links: Dict of equipment names to their documentation URLs
        bilingual: Emit toggleable IT/EN bilingual HTML (see HTMLGenerator).
        use_online: Enable the online (deep-translator) MT fallback. False =
            offline / glossary only.

    Returns:
        The generated HTML string
    """
    generator = HTMLGenerator(
        controller,
        translate=translate,
        navigation_links=navigation_links,
        inline_assets=inline_assets,
        bilingual=bilingual,
        use_online=use_online,
    )
    return generator.generate(output_path)
