"use client";

import { ArrowUpRight, Menu, X } from "lucide-react";
import { useState } from "react";
import { Brand } from "./icons";
import { ThemeControl } from "./ThemeControl";

export function Header() {
  const [open, setOpen] = useState(false);

  const close = () => setOpen(false);

  return (
    <header className="site-header">
      <div className="container header-inner">
        <Brand />
        <nav className={`nav-links ${open ? "is-open" : ""}`} id="main-nav" aria-label="Main navigation">
          <a href="/#playground" onClick={close}>
            Playground
          </a>
          <a href="/#examples" onClick={close}>
            Examples
          </a>
          <a href="/#developers" onClick={close}>
            For developers
          </a>
          <a href="/use-cases" onClick={close}>Use cases</a>
        </nav>
        <div className="header-actions">
          <ThemeControl />
          <a className="btn btn-primary btn-small header-cta" href="/#playground">
            Try for free <ArrowUpRight aria-hidden="true" />
          </a>
          <button
            className="icon-btn mobile-toggle"
            type="button"
            aria-controls="main-nav"
            aria-expanded={open}
            aria-label={open ? "Close navigation" : "Open navigation"}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          </button>
        </div>
      </div>
    </header>
  );
}
