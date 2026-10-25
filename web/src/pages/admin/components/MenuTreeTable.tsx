// 共享两级树表（spec §19）：页面行 + 缩进按钮子行，行首折叠箭头——
// 菜单管理（编辑控件渲染）与权限管理（Checkbox 授权渲染）复用同一骨架，
// 单元格内容由两页各自传入（克制抽象：只管树形，不管业务）
import { Fragment, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, MousePointerClick } from 'lucide-react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { MenuDef } from '@/lib/api'

export function MenuTreeTable({ menus, columns, renderPage, renderButton, hint }: {
  menus: MenuDef[]
  /** 折叠箭头列之后的表头（列布局由两页约定一致） */
  columns: string[]
  /** 页面行单元格（不含折叠箭头列）；btns = 挂其下的按钮条 */
  renderPage: (m: MenuDef, btns: MenuDef[]) => ReactNode
  /** 按钮子行单元格（不含缩进图标列） */
  renderButton: (b: MenuDef) => ReactNode
  /** 表尾说明（如按钮可见性语义） */
  hint?: ReactNode
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const pages = menus.filter((m) => m.type !== 'button').sort((a, b) => a.sort - b.sort)
  const toggle = (path: string) =>
    setCollapsed((s) => {
      const n = new Set(s)
      if (s.has(path)) n.delete(path); else n.add(path)
      return n
    })

  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8" />
            {columns.map((h) => <TableHead key={h}>{h}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {pages.map((m) => {
            const btns = menus
              .filter((x) => x.type === 'button' && x.parent === m.path)
              .sort((a, b) => a.sort - b.sort)
            const open = !collapsed.has(m.path)
            return (
              <Fragment key={m.path}>
                <TableRow>
                  <TableCell className="w-8">
                    {btns.length > 0 ? (
                      <button aria-label="展开/收起" className="text-muted-foreground"
                              onClick={() => toggle(m.path)}>
                        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                      </button>
                    ) : (
                      <span className="inline-block size-4" />
                    )}
                  </TableCell>
                  {renderPage(m, btns)}
                </TableRow>
                {open && btns.map((b) => (
                  <TableRow key={b.path} className="bg-muted/30 hover:bg-muted/30">
                    <TableCell className="w-8">
                      <MousePointerClick className="ml-3 size-3.5 text-muted-foreground/70" />
                    </TableCell>
                    {renderButton(b)}
                  </TableRow>
                ))}
              </Fragment>
            )
          })}
        </TableBody>
      </Table>
      {hint && <div className="px-3 py-2.5 text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  )
}
