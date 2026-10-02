import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  SparkleIcon,
  HomeIcon,
  GridIcon,
  MailIcon,
  DiamondIcon,
  TargetIcon,
  SearchIcon,
  BellIcon,
  MapPinIcon,
  LayoutIcon,
  InboxIcon,
  UsersIcon,
  WalletIcon,
  ChartIcon,
  SettingsIcon,
  HelpIcon,
  PlusIcon,
  MenuIcon,
  XIcon,
  RupeeIcon,
  TicketIcon,
  AlertIcon,
  ClockIcon,
  LinkedInIcon,
  TwitterIcon,
  YouTubeIcon,
} from './icons'

/* ------------------------------------------------------------------ */
/* Reveal-on-scroll                                                    */
/* ------------------------------------------------------------------ */
function Reveal({
  children,
  delay = 0,
  className = '',
}: {
  children: ReactNode
  delay?: number
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setTimeout(() => setVisible(true), delay)
            obs.disconnect()
          }
        }
      },
      { threshold: 0.12 },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [delay])

  return (
    <div ref={ref} className={`reveal ${visible ? 'is-visible' : ''} ${className}`}>
      {children}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Section header                                                      */
/* ------------------------------------------------------------------ */
function SectionHeader({ eyebrow, title, sub }: { eyebrow: string; title: string; sub?: string }) {
  return (
    <div className="section-header">
      <Reveal>
        <span className="eyebrow">{eyebrow}</span>
      </Reveal>
      <Reveal delay={80}>
        <h2>{title}</h2>
      </Reveal>
      {sub && (
        <Reveal delay={140}>
          <p>{sub}</p>
        </Reveal>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Dashboard mockup data (shared between laptop + phone)               */
/* ------------------------------------------------------------------ */
const NAV = [
  { label: 'Dashboard', icon: LayoutIcon, active: true },
  { label: 'Operations', icon: InboxIcon },
  { label: 'Workforce', icon: UsersIcon },
  { label: 'Finance', icon: WalletIcon },
  { label: 'Reports', icon: ChartIcon },
  { label: 'Settings', icon: SettingsIcon },
  { label: 'Support', icon: HelpIcon },
]

const SUBNAV: Record<string, string[]> = {
  Operations: ['Request Queue', 'Assignment Center', 'Live Jobs'],
  Workforce: ['Employees', 'IT Tasks'],
  Finance: ['Expense Dashboard', 'Invoices', 'Payers', 'Statements'],
}

const KPIS = [
  {
    icon: RupeeIcon,
    tint: 'red',
    value: '₹7,82,500',
    label: 'Monthly Revenue',
    delta: '+24% from last month',
    deltaClass: '',
  },
  {
    icon: TicketIcon,
    tint: 'green',
    value: '156',
    label: 'Tickets Resolved',
    delta: '87.2% resolution rate',
    deltaClass: '',
  },
  {
    icon: AlertIcon,
    tint: 'amber',
    value: '23',
    label: 'Open Tickets',
    delta: '5 critical',
    deltaClass: 'crit',
  },
  {
    icon: ClockIcon,
    tint: 'blue',
    value: '94.5%',
    label: 'SLA Compliance',
    delta: 'Avg. response: 48 min',
    deltaClass: 'warn',
  },
]

const CATEGORIES = [
  { count: 34, name: 'IT Support', width: '88%', cls: '' },
  { count: 18, name: 'Network & Infra', width: '47%', cls: 'alt' },
  { count: 12, name: 'Cloud Services', width: '31%', cls: 'alt2' },
  { count: 8, name: 'Cybersecurity', width: '21%', cls: 'alt2' },
]

const TICKETS = [
  { name: 'Server Maintenance', client: 'TechCorp', status: 'In Progress', cls: 'progress' },
  { name: 'VPN Setup & Configuration', client: 'StartupX', status: 'Completed', cls: 'done' },
  { name: 'Data Recovery', client: 'Infosys Branch Office', status: 'Pending', cls: 'pending' },
]

const PERFORMANCE = [
  { label: 'Monthly Revenue Target', value: '82%', cls: '' },
  { label: 'Ticket Resolution Rate', value: '87%', cls: 'soft' },
  { label: 'Client Satisfaction', value: '94%', cls: 'green' },
  { label: 'SLA Compliance', value: '95%', cls: 'blue' },
]

/* ------------------------------------------------------------------ */
/* Dashboard mockup pieces                                             */
/* ------------------------------------------------------------------ */
function DashboardSidebar() {
  return (
    <aside className="dash-sidebar">
      <div className="dash-brand">
        <span className="dash-brand-mark">RZ</span>
        <span className="dash-brand-name">Ricoz</span>
      </div>
      <span className="dash-loc">
        <MapPinIcon size={10} />
        Mumbai West
      </span>
      {NAV.map((item) => (
        <span key={item.label} style={{ display: 'contents' }}>
          <span className={`dash-nav-item ${item.active ? 'active' : ''}`}>
            <item.icon size={13} />
            {item.label}
          </span>
          {SUBNAV[item.label]?.map((sub) => (
            <span key={sub} className="dash-nav-item dash-nav-sub">
              {sub}
            </span>
          ))}
        </span>
      ))}
    </aside>
  )
}

function DashboardTopbar() {
  return (
    <div className="dash-top">
      <div className="dash-hello">
        <h4>Dashboard</h4>
        <span>Welcome back, Amit! Here's your IT operations overview</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="dash-search">
          <SearchIcon size={11} />
          Search tickets, clients…
        </span>
        <span className="dash-bell">
          <BellIcon size={13} />
        </span>
        <span className="dash-user">
          <span className="dash-avatar">AK</span>
          <span className="dash-user-meta">
            <b>Amit Kumar</b>
            <span>Franchise Admin</span>
          </span>
        </span>
      </div>
    </div>
  )
}

function DashboardLaptop() {
  return (
    <div className="laptop">
      <div className="dash">
        <DashboardSidebar />
        <div className="dash-main">
          <DashboardTopbar />
          <div className="dash-kpis">
            {KPIS.map((k) => (
              <div className="dash-kpi" key={k.label}>
                <div className="dash-kpi-top">
                  <span className={`dash-kpi-icon ${k.tint}`}>
                    <k.icon size={13} />
                  </span>
                </div>
                <span className="dash-kpi-value">{k.value}</span>
                <span className="dash-kpi-label">{k.label}</span>
                <span className={`dash-kpi-delta ${k.deltaClass}`}>{k.delta}</span>
              </div>
            ))}
          </div>
          <div className="dash-cols">
            <div className="dash-panel">
              <span className="dash-panel-title">Active Work by Category</span>
              {CATEGORIES.map((c) => (
                <div className="dash-cat" key={c.name}>
                  <span className="dash-cat-count">{c.count}</span>
                  <span className="dash-cat-meta">
                    <span className="dash-cat-name">{c.name}</span>
                    <span className="dash-cat-bar">
                      <span className={`dash-cat-fill ${c.cls}`} style={{ width: c.width }} />
                    </span>
                  </span>
                </div>
              ))}
            </div>
            <div className="dash-panel">
              <span className="dash-panel-title">Recent Tickets</span>
              {TICKETS.map((t) => (
                <div className="dash-ticket" key={t.name}>
                  <span>
                    <span className="dash-ticket-name">{t.name}</span>
                    <br />
                    <span className="dash-ticket-client">{t.client}</span>
                  </span>
                  <span className={`dash-badge ${t.cls}`}>{t.status}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="dash-panel">
            <span className="dash-panel-title">Performance Overview</span>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {PERFORMANCE.map((p) => (
                <div className="dash-perf-row" key={p.label}>
                  <span className="dash-perf-head">
                    <span>{p.label}</span>
                    <span>{p.value}</span>
                  </span>
                  <span className="dash-perf-track">
                    <span className={`dash-perf-fill ${p.cls}`} style={{ width: p.value }} />
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function DashboardPhone() {
  return (
    <div className="phone">
      <div className="dash">
        <div className="dash-main" style={{ padding: 14, gap: 10 }}>
          <div className="dash-top" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 8 }}>
            <div className="dash-hello">
              <h4 style={{ fontSize: 14 }}>Dashboard</h4>
              <span style={{ fontSize: 9.5 }}>Welcome back, Amit</span>
            </div>
            <span className="dash-user">
              <span className="dash-avatar" style={{ width: 26, height: 26, fontSize: 10 }}>AK</span>
              <span className="dash-user-meta">
                <b style={{ fontSize: 10.5 }}>Amit Kumar</b>
                <span style={{ fontSize: 9 }}>Franchise Admin</span>
              </span>
            </span>
          </div>
          <div className="dash-kpis" style={{ gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {KPIS.slice(0, 2).map((k) => (
              <div className="dash-kpi" key={k.label} style={{ padding: 10 }}>
                <span className="dash-kpi-value" style={{ fontSize: 15 }}>{k.value}</span>
                <span className="dash-kpi-label" style={{ fontSize: 9 }}>{k.label}</span>
                <span className={`dash-kpi-delta ${k.deltaClass}`} style={{ fontSize: 8.5 }}>{k.delta}</span>
              </div>
            ))}
          </div>
          <div className="dash-panel" style={{ padding: 10 }}>
            <span className="dash-panel-title" style={{ fontSize: 11 }}>Recent Tickets</span>
            {TICKETS.map((t) => (
              <div className="dash-ticket" key={t.name} style={{ padding: '7px 0' }}>
                <span>
                  <span className="dash-ticket-name" style={{ fontSize: 10 }}>{t.name}</span>
                  <br />
                  <span className="dash-ticket-client" style={{ fontSize: 9 }}>{t.client}</span>
                </span>
                <span className={`dash-badge ${t.cls}`} style={{ fontSize: 8.5 }}>{t.status}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function ProductShowcase() {
  return (
    <div className="showcase-visual">
      <DashboardLaptop />
      <DashboardPhone />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Page content                                                        */
/* ------------------------------------------------------------------ */
const FEATURES = [
  {
    icon: SparkleIcon,
    title: 'Centralized Lead Generation',
    desc: 'Receive customer inquiries through a unified platform and focus on converting opportunities into successful projects.',
  },
  {
    icon: HomeIcon,
    title: 'Complete Operational Support',
    desc: 'Get assistance with business operations, workflows and service delivery so you can run your franchise with confidence.',
  },
  {
    icon: GridIcon,
    title: 'Technology-Powered Platform',
    desc: 'Manage leads, projects, teams, finances and performance from a single business dashboard.',
  },
  {
    icon: MailIcon,
    title: 'Training & Business Development',
    desc: 'Access structured onboarding, operational guidance and continuous learning resources designed for franchise growth.',
  },
  {
    icon: DiamondIcon,
    title: 'Marketing & Brand Support',
    desc: 'Leverage centralized marketing initiatives, promotional campaigns and brand assets to strengthen your local presence.',
  },
  {
    icon: TargetIcon,
    title: 'Dedicated Partner Success Team',
    desc: 'Our support teams work alongside you to resolve challenges, improve performance and help your business scale efficiently.',
  },
]

const FAQS = [
  {
    q: 'What support does Ricoz provide?',
    a: 'Every franchise partner gets end-to-end support — technology, operations, training, marketing and a dedicated partner success team. From your first lead to your latest invoice, the platform and the people behind it stay with you at every stage.',
  },
  {
    q: 'Is training provided before launch?',
    a: 'Yes. Structured onboarding covers the platform, service delivery, local marketing and business operations, so your team is ready before day one — plus continuous learning resources as you grow.',
  },
  {
    q: 'How do customer leads reach franchise partners?',
    a: 'Leads generated through Ricoz channels are routed to your location through the unified lead platform, with clear assignment, tracking and follow-up tools built into the dashboard.',
  },
  {
    q: 'Can I operate multiple service categories?',
    a: 'Absolutely. Many partners operate across IT support, network infrastructure, cloud services and cybersecurity — the platform tracks each category separately while you manage everything in one place.',
  },
  {
    q: 'How long does the onboarding process take?',
    a: 'Most partners go from agreement to fully operational in 4–6 weeks, including setup, training and launch marketing support. Your partner success team keeps the timeline on track.',
  },
]

export default function App() {
  const [scrolled, setScrolled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [openFaq, setOpenFaq] = useState<number | null>(0)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      {/* ---------------- Header ---------------- */}
      <header className={`site-header ${scrolled ? 'is-scrolled' : ''}`}>
        <div className="container header-inner">
          <a href="#" className="brand" aria-label="Ricoz home">
            <span className="brand-mark">RZ</span>
            <span className="brand-name">Ricoz</span>
          </a>
          <nav className={`nav-actions ${menuOpen ? 'mobile-open' : ''}`} aria-label="Primary">
            <a href="#contact" className="btn btn-outline">
              Get in Touch
            </a>
            <a href="#partner" className="btn btn-primary">
              Become a Franchise Partner
            </a>
            <span className="header-divider" aria-hidden="true" />
            <a href="#login" className="btn btn-ghost-red">
              Franchise Login
            </a>
          </nav>
          <button
            className="nav-toggle"
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            {menuOpen ? <XIcon size={18} /> : <MenuIcon size={18} />}
          </button>
        </div>
      </header>

      <main id="main">
        {/* ---------------- Hero ---------------- */}
        <section className="hero">
          <div className="container">
            <Reveal>
              <span className="eyebrow">Built for Modern Entrepreneurs</span>
            </Reveal>
            <Reveal delay={80}>
              <h1>
                Build. Manage. Grow. <span className="accent">With Confidence.</span>
              </h1>
            </Reveal>
            <Reveal delay={140}>
              <p className="hero-sub">
                Launch, manage and grow your business with a complete ecosystem designed for modern
                entrepreneurs.
              </p>
            </Reveal>
            <Reveal delay={200}>
              <div className="hero-ctas">
                <a href="#partner" className="btn btn-primary">
                  Become a Franchise Partner
                </a>
                <a href="#contact" className="btn btn-outline">
                  Get in Touch
                </a>
              </div>
            </Reveal>
          </div>
          <div className="container hero-visual">
            <Reveal delay={260}>
              <ProductShowcase />
            </Reveal>
          </div>
        </section>

        {/* ---------------- Features ---------------- */}
        <section className="section" id="features">
          <div className="container">
            <SectionHeader
              eyebrow="Why Ricoz"
              title="Everything You Need To Build A Successful Franchise Business"
              sub="Launch, manage and grow your business with a complete ecosystem designed for modern entrepreneurs. From technology and training to marketing and operational support, Ricoz helps you succeed at every stage."
            />
            <div className="feature-grid">
              {FEATURES.map((f, i) => (
                <Reveal key={f.title} delay={(i % 3) * 70}>
                  <div className="feature-card">
                    <span className="feature-icon">
                      <f.icon size={22} />
                    </span>
                    <h3>{f.title}</h3>
                    <p>{f.desc}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ---------------- Product showcase ---------------- */}
        <section className="section section-alt" id="platform">
          <div className="container">
            <SectionHeader
              eyebrow="Franchise Platform"
              title="One Platform. Complete Franchise Management."
              sub="Manage leads, projects, finances, operations and performance from a centralized dashboard designed to help franchise partners run and grow their business with confidence."
            />
            <Reveal>
              <ProductShowcase />
            </Reveal>
          </div>
        </section>

        {/* ---------------- Testimonial ---------------- */}
        <section className="section" id="testimonials">
          <div className="container">
            <Reveal>
              <div className="testimonial">
                <div className="testimonial-mark" aria-hidden="true">
                  “
                </div>
                <blockquote>
                  Ricoz gave us the platform, the training and the confidence to run our business
                  like an established brand — from day one.
                </blockquote>
                <div className="testimonial-person">
                  <span className="testimonial-avatar">RS</span>
                  <b>Franchise Partner</b>
                  <span>Ricoz Network</span>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ---------------- FAQ ---------------- */}
        <section className="section section-alt" id="faq">
          <div className="container">
            <SectionHeader eyebrow="FAQ" title="Frequently Asked Questions" />
            <div className="faq">
              {FAQS.map((f, i) => {
                const open = openFaq === i
                return (
                  <div className={`faq-item ${open ? 'open' : ''}`} key={f.q}>
                    <button
                      className="faq-q"
                      aria-expanded={open}
                      aria-controls={`faq-a-${i}`}
                      onClick={() => setOpenFaq(open ? null : i)}
                    >
                      <span>{f.q}</span>
                      <span className="faq-icon" aria-hidden="true">
                        <PlusIcon size={14} />
                      </span>
                    </button>
                    <div className="faq-a" id={`faq-a-${i}`}>
                      <p>{f.a}</p>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* CTA card */}
            <div className="cta-card" id="contact">
              <div className="cta-avatars" aria-hidden="true">
                <span className="dash-avatar">PS</span>
                <span className="dash-avatar">MT</span>
                <span className="dash-avatar">RK</span>
              </div>
              <h2>Still have questions?</h2>
              <p>
                Our franchise team is here to help you understand the opportunity, investment
                requirements and growth potential.
              </p>
              <a href="#partner" className="btn btn-primary">
                Talk to Our Franchise Team
              </a>
            </div>
          </div>
        </section>
      </main>

      {/* ---------------- Footer ---------------- */}
      <footer className="site-footer" id="partner">
        <div className="container">
          <div className="footer-grid">
            <div className="footer-brand">
              <a href="#" className="brand" aria-label="Ricoz home">
                <span className="brand-mark">RZ</span>
                <span className="brand-name">Ricoz</span>
              </a>
              <p>
                A complete ecosystem for modern entrepreneurs — technology, training, marketing and
                operational support to build and grow a successful franchise business.
              </p>
            </div>
            <div className="footer-col">
              <h5>Product</h5>
              <ul>
                <li>
                  <a href="#platform">Platform</a>
                </li>
                <li>
                  <a href="#features">Features</a>
                </li>
                <li>
                  <a href="#faq">FAQ</a>
                </li>
              </ul>
            </div>
            <div className="footer-col">
              <h5>Company</h5>
              <ul>
                <li>
                  <a href="#contact">Contact</a>
                </li>
                <li>
                  <a href="#partner">Partner With Us</a>
                </li>
              </ul>
            </div>
            <div className="footer-col">
              <h5>Resources</h5>
              <ul>
                <li>
                  <a href="#faq">Help Center</a>
                </li>
                <li>
                  <a href="#testimonials">Partner Stories</a>
                </li>
              </ul>
            </div>
            <div className="footer-col">
              <h5>Legal</h5>
              <ul>
                <li>
                  <a href="#">Privacy Policy</a>
                </li>
                <li>
                  <a href="#">Terms of Service</a>
                </li>
              </ul>
            </div>
          </div>
          <div className="footer-bottom">
            <span>© {new Date().getFullYear()} Ricoz. All rights reserved.</span>
            <div className="footer-social">
              <a href="#" aria-label="LinkedIn">
                <LinkedInIcon size={15} />
              </a>
              <a href="#" aria-label="Twitter / X">
                <TwitterIcon size={15} />
              </a>
              <a href="#" aria-label="YouTube">
                <YouTubeIcon size={15} />
              </a>
            </div>
          </div>
        </div>
      </footer>
    </>
  )
}
