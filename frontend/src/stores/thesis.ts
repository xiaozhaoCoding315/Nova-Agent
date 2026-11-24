import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type {
  ThesisCitationAudit,
  ThesisCitationEvidence,
  ThesisDisclosure,
  ThesisDisclosureInput,
  ThesisDocument,
  ThesisDocumentDetail,
  ThesisFix,
  ThesisFixPreview,
  ThesisIssue,
  ThesisProject,
  ThesisProjectDetail,
  ThesisProjectInput,
  ThesisReferencePdf,
  ThesisReport,
  ThesisScanResult,
  ThesisTemplate,
} from '../lib/types'

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

/** 切换项目/登出后丢弃迟到的旧项目响应，避免覆盖新项目的面板数据。 */
let thesisEpoch = 0

type ThesisState = {
  projects: ThesisProject[]
  templates: ThesisTemplate[]
  current: ThesisProjectDetail | null
  document: ThesisDocumentDetail | null
  issues: ThesisIssue[]
  fixes: ThesisFix[]
  citations: ThesisCitationAudit | null
  referencePdfs: ThesisReferencePdf[]
  evidence: ThesisCitationEvidence[]
  disclosures: ThesisDisclosure[]
  report: ThesisReport | null
  scan: ThesisScanResult | null
  /** 写作面板的快捷指令：AI 对话面板监听后填入输入框。 */
  chatSeed: string
  /** AI 对话里点「记入 AI 使用声明」时预填的草稿，由声明面板消费。 */
  disclosureDraft: ThesisDisclosureInput | null
  seedDisclosure: (input: ThesisDisclosureInput) => void
  clearDisclosureDraft: () => void
  loading: boolean
  busy: boolean
  fixing: string | null
  error: string | null
  reset: () => void
  setChatSeed: (seed: string) => void
  updateProject: (patch: Partial<ThesisProjectInput>) => Promise<void>
  refresh: () => Promise<void>
  loadTemplates: () => Promise<void>
  selectProject: (id: string) => Promise<void>
  createProject: (input: ThesisProjectInput) => Promise<ThesisProject>
  removeProject: (id: string) => Promise<void>
  uploadDocument: (file: File) => Promise<ThesisDocument | null>
  scanProject: () => Promise<void>
  previewFix: (issueId: string) => Promise<ThesisFixPreview>
  applyFix: (issueId: string) => Promise<void>
  undoFix: (issueId: string) => Promise<void>
  setIssueStatus: (issueId: string, status: 'open' | 'ignored') => Promise<void>
  refreshCitations: () => Promise<void>
  auditCitations: () => Promise<void>
  verifyMetadata: () => Promise<void>
  uploadReferencePdf: (file: File) => Promise<void>
  deleteReferencePdf: (pdfId: string) => Promise<void>
  locateEvidence: () => Promise<void>
  updateEvidence: (evidenceId: string, support: string, note?: string) => Promise<void>
  loadDisclosures: () => Promise<void>
  addDisclosure: (input: ThesisDisclosureInput) => Promise<void>
  removeDisclosure: (id: string) => Promise<void>
  exportReport: (format: 'html' | 'docx') => Promise<void>
  exportPackage: () => Promise<void>
  clearError: () => void
}

export const useThesis = create<ThesisState>((set, get) => ({
  projects: [],
  templates: [],
  current: null,
  document: null,
  issues: [],
  fixes: [],
  citations: null,
  referencePdfs: [],
  evidence: [],
  disclosures: [],
  report: null,
  scan: null,
  chatSeed: '',
  disclosureDraft: null,
  loading: false,
  busy: false,
  fixing: null,
  error: null,

  clearError: () => set({ error: null }),

  seedDisclosure: (disclosureDraft) => set({ disclosureDraft }),
  clearDisclosureDraft: () => set({ disclosureDraft: null }),

  // 论文项目是账号私有数据；登出/换号时必须清空，不能留给下一个账号。
  reset: () => {
    thesisEpoch += 1
    set({
      projects: [],
      templates: [],
      current: null,
      document: null,
      issues: [],
      fixes: [],
      citations: null,
      referencePdfs: [],
      evidence: [],
      disclosures: [],
      report: null,
      scan: null,
      chatSeed: '',
      disclosureDraft: null,
      loading: false,
      busy: false,
      fixing: null,
      error: null,
    })
  },

  setChatSeed: (chatSeed) => set({ chatSeed }),

  updateProject: async (patch) => {
    const current = get().current
    if (!current) return
    try {
      const updated = await api.thesis.updateProject(current.id, patch)
      set((state) => ({
        current: state.current ? { ...state.current, ...updated } : state.current,
        projects: state.projects.map((item) =>
          item.id === updated.id ? { ...item, ...updated } : item,
        ),
      }))
    } catch (err) {
      set({ error: errorMessage(err, '保存论文项目失败') })
      throw err
    }
  },

  loadTemplates: async () => {
    if (get().templates.length > 0) return
    try {
      set({ templates: await api.thesis.templates() })
    } catch (err) {
      set({ error: errorMessage(err, '加载论文模板失败') })
    }
  },

  refresh: async () => {
    const epoch = thesisEpoch
    set({ loading: true, error: null })
    try {
      const [projects, templates] = await Promise.all([
        api.thesis.projects(),
        get().templates.length > 0 ? Promise.resolve(get().templates) : api.thesis.templates(),
      ])
      if (epoch !== thesisEpoch) return
      set({ projects, templates, loading: false })
    } catch (err) {
      if (epoch !== thesisEpoch) return
      set({ loading: false, error: errorMessage(err, '加载论文项目失败') })
    }
  },

  selectProject: async (id) => {
    const epoch = ++thesisEpoch
    set({
      loading: true,
      error: null,
      current: null,
      document: null,
      issues: [],
      fixes: [],
      citations: null,
      referencePdfs: [],
      evidence: [],
      disclosures: [],
      report: null,
      scan: null,
    })
    try {
      const [current, fixes, citations, referencePdfs, evidence, disclosures] =
        await Promise.all([
          api.thesis.project(id),
          api.thesis.fixes(id).catch(() => [] as ThesisFix[]),
          api.thesis.citations(id).catch(() => null),
          api.thesis.referencePdfs(id).catch(() => [] as ThesisReferencePdf[]),
          api.thesis.citationEvidence(id).catch(() => [] as ThesisCitationEvidence[]),
          api.thesis.disclosures(id).catch(() => [] as ThesisDisclosure[]),
        ])
      if (epoch !== thesisEpoch) return
      const latest = current.documents[0]
      let document: ThesisDocumentDetail | null = null
      let issues: ThesisIssue[] = []
      let report: ThesisReport | null = null
      if (latest) {
        const [doc, issueList, reportData] = await Promise.all([
          api.thesis.document(latest.id),
          api.thesis.issues(id, 'all').catch(() => [] as ThesisIssue[]),
          api.thesis.report(id).catch(() => null),
        ])
        if (epoch !== thesisEpoch) return
        document = doc
        issues = issueList
        report = reportData
      }
      set({
        current,
        document,
        issues,
        fixes,
        citations,
        referencePdfs,
        evidence,
        disclosures,
        report,
        loading: false,
      })
    } catch (err) {
      if (epoch !== thesisEpoch) return
      set({ loading: false, error: errorMessage(err, '加载论文项目失败') })
    }
  },

  createProject: async (input) => {
    set({ error: null, busy: true })
    try {
      const project = await api.thesis.createProject(input)
      const projects = await api.thesis.projects()
      set({ projects, busy: false })
      await get().selectProject(project.id)
      return project
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '创建论文项目失败') })
      throw err
    }
  },

  removeProject: async (id) => {
    set({ error: null })
    try {
      await api.thesis.removeProject(id)
      const projects = get().projects.filter((project) => project.id !== id)
      set({ projects })
      if (get().current?.id === id) {
        set({
          current: null,
          document: null,
          issues: [],
          fixes: [],
          citations: null,
          referencePdfs: [],
          evidence: [],
          disclosures: [],
          report: null,
          scan: null,
        })
      }
    } catch (err) {
      set({ error: errorMessage(err, '删除论文项目失败') })
    }
  },

  uploadDocument: async (file) => {
    const project = get().current
    if (!project) {
      set({ error: '请先选择一个论文项目' })
      return null
    }
    set({ error: null, busy: true })
    try {
      const uploaded = await api.thesis.uploadDocument(project.id, file)
      await get().selectProject(project.id)
      set({ busy: false, scan: null })
      return uploaded
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '导入 DOCX 失败') })
      return null
    }
  },

  scanProject: async () => {
    const project = get().current
    if (!project) {
      set({ error: '请先选择一个论文项目' })
      return
    }
    set({ error: null, busy: true })
    try {
      const scan = await api.thesis.scan(project.id, project.template_id)
      const [report, projects, citations, fixes] = await Promise.all([
        api.thesis.report(project.id).catch(() => null),
        api.thesis.projects().catch(() => get().projects),
        api.thesis.citations(project.id).catch(() => null),
        api.thesis.fixes(project.id).catch(() => get().fixes),
      ])
      set({
        scan,
        issues: scan.issues,
        report,
        projects,
        citations,
        fixes,
        busy: false,
      })
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '检查失败') })
    }
  },

  previewFix: async (issueId) => {
    set({ error: null })
    try {
      return await api.thesis.previewFix(issueId)
    } catch (err) {
      set({ error: errorMessage(err, '预览修复失败') })
      throw err
    }
  },

  applyFix: async (issueId) => {
    const project = get().current
    if (!project) return
    set({ error: null, fixing: issueId })
    try {
      const result = await api.thesis.applyFix(issueId)
      const [document, report, projects, citations, fixes] = await Promise.all([
        api.thesis.document(result.document.id).catch(() => get().document),
        api.thesis.report(project.id).catch(() => get().report),
        api.thesis.projects().catch(() => get().projects),
        api.thesis.citations(project.id).catch(() => get().citations),
        api.thesis.fixes(project.id).catch(() => get().fixes),
      ])
      set((state) => ({
        fixing: null,
        document,
        report,
        projects,
        citations,
        fixes,
        issues: state.issues.map((issue) => (issue.id === issueId ? result.issue : issue)),
      }))
    } catch (err) {
      set({ fixing: null, error: errorMessage(err, '应用修复失败') })
      throw err
    }
  },

  undoFix: async (issueId) => {
    const project = get().current
    if (!project) return
    set({ error: null, fixing: issueId })
    try {
      const result = await api.thesis.undoFix(issueId)
      const [document, report, projects, citations, fixes] = await Promise.all([
        api.thesis.document(result.document.id).catch(() => get().document),
        api.thesis.report(project.id).catch(() => get().report),
        api.thesis.projects().catch(() => get().projects),
        api.thesis.citations(project.id).catch(() => get().citations),
        api.thesis.fixes(project.id).catch(() => get().fixes),
      ])
      set((state) => ({
        fixing: null,
        document,
        report,
        projects,
        citations,
        fixes,
        issues: state.issues.map((issue) => (issue.id === issueId ? result.issue : issue)),
      }))
    } catch (err) {
      set({ fixing: null, error: errorMessage(err, '撤销修复失败') })
      throw err
    }
  },

  setIssueStatus: async (issueId, status) => {
    const project = get().current
    if (!project) return
    set({ error: null, fixing: issueId })
    try {
      const issue = await api.thesis.updateIssue(issueId, status)
      const [report, projects] = await Promise.all([
        api.thesis.report(project.id).catch(() => get().report),
        api.thesis.projects().catch(() => get().projects),
      ])
      set((state) => ({
        fixing: null,
        report,
        projects,
        issues: state.issues.map((item) => (item.id === issueId ? issue : item)),
      }))
    } catch (err) {
      set({ fixing: null, error: errorMessage(err, '更新问题状态失败') })
      throw err
    }
  },

  refreshCitations: async () => {
    const project = get().current
    if (!project) return
    try {
      set({ citations: await api.thesis.citations(project.id) })
    } catch (err) {
      set({ error: errorMessage(err, '加载引用结果失败') })
    }
  },

  auditCitations: async () => {
    const project = get().current
    if (!project) return
    set({ error: null, busy: true })
    try {
      const citations = await api.thesis.auditCitations(project.id)
      set({ citations, busy: false })
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '引用核对失败') })
    }
  },

  verifyMetadata: async () => {
    const project = get().current
    if (!project) return
    set({ error: null, busy: true })
    try {
      const citations = await api.thesis.verifyMetadata(project.id)
      set({ citations, busy: false })
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '联网核验元数据失败') })
    }
  },

  uploadReferencePdf: async (file) => {
    const project = get().current
    if (!project) {
      set({ error: '请先选择一个论文项目' })
      return
    }
    set({ error: null, busy: true })
    try {
      const pdf = await api.thesis.uploadReferencePdf(project.id, file)
      set((state) => ({ busy: false, referencePdfs: [...state.referencePdfs, pdf] }))
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '上传参考文献 PDF 失败') })
      throw err
    }
  },

  deleteReferencePdf: async (pdfId) => {
    const project = get().current
    if (!project) return
    set({ error: null, busy: true })
    try {
      await api.thesis.deleteReferencePdf(pdfId)
      set((state) => ({
        busy: false,
        referencePdfs: state.referencePdfs.filter((pdf) => pdf.id !== pdfId),
        evidence: state.evidence.filter((item) => item.pdf_id !== pdfId),
      }))
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '删除参考文献 PDF 失败') })
    }
  },

  locateEvidence: async () => {
    const project = get().current
    if (!project) return
    set({ error: null, busy: true })
    try {
      const result = await api.thesis.locateEvidence(project.id)
      set({
        busy: false,
        evidence: result.evidence,
        referencePdfs: result.pdfs,
      })
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '全文证据定位失败') })
    }
  },

  updateEvidence: async (evidenceId, support, note) => {
    set({ error: null })
    try {
      const updated = await api.thesis.updateEvidence(evidenceId, support, note)
      set((state) => ({
        evidence: state.evidence.map((item) => (item.id === evidenceId ? updated : item)),
      }))
    } catch (err) {
      set({ error: errorMessage(err, '更新证据状态失败') })
    }
  },

  loadDisclosures: async () => {
    const project = get().current
    if (!project) return
    try {
      set({ disclosures: await api.thesis.disclosures(project.id) })
    } catch (err) {
      set({ error: errorMessage(err, '加载 AI 使用记录失败') })
    }
  },

  addDisclosure: async (input) => {
    const project = get().current
    if (!project) return
    set({ error: null, busy: true })
    try {
      const disclosure = await api.thesis.createDisclosure(project.id, input)
      set((state) => ({
        busy: false,
        disclosures: [...state.disclosures, disclosure],
      }))
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '保存 AI 使用记录失败') })
      throw err
    }
  },

  removeDisclosure: async (id) => {
    set({ error: null })
    try {
      await api.thesis.deleteDisclosure(id)
      set((state) => ({ disclosures: state.disclosures.filter((item) => item.id !== id) }))
    } catch (err) {
      set({ error: errorMessage(err, '删除 AI 使用记录失败') })
    }
  },

  exportReport: async (format) => {
    const project = get().current
    if (!project) return
    set({ error: null, busy: true })
    try {
      await api.thesis.exportReport(project.id, format)
      set({ busy: false })
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '导出报告失败') })
    }
  },

  exportPackage: async () => {
    const project = get().current
    if (!project) return
    set({ error: null, busy: true })
    try {
      const readiness = await api.thesis.exportReadiness(project.id)
      if (!readiness.ready) {
        const lines = readiness.warnings
          .slice(0, 6)
          .map((item) => `· ${item.message}`)
          .join('\n')
        const proceed = window.confirm(
          `导出前检查到以下未确认项：\n${lines}\n\n仍然导出？建议先回「阶段」页确认；` +
          '已失效的确认不会因为导出而恢复。',
        )
        if (!proceed) {
          set({ busy: false })
          return
        }
        await api.thesis.exportPackage(project.id, true)
      } else {
        await api.thesis.exportPackage(project.id)
      }
      set({ busy: false })
    } catch (err) {
      set({ busy: false, error: errorMessage(err, '导出定稿包失败') })
    }
  },
}))
