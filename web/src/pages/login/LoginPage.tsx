// 登录页（spec §2）：服务端认证——POST /auth/login 换 HttpOnly 会话 cookie
// 账号由管理员经 scripts/init_users.py 开通；前端不再持有任何账号表
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useSession } from '@/lib/session'

export function LoginPage() {
  const { login } = useSession()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!name.trim() || !password || busy) return
    setBusy(true); setErr('')
    try {
      await login(name.trim(), password)
      navigate('/', { replace: true })
    } catch (e) {
      setErr(`${e}`.replace(/^Error: /, ''))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl font-extrabold tracking-wide">AdKG</CardTitle>
          <CardDescription>本体驱动的广告营销知识中台</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="account">账号</Label>
            <Input id="account" value={name} autoComplete="username"
                   placeholder="账号由管理员开通"
                   onChange={(e) => { setName(e.target.value); setErr('') }}
                   onKeyDown={(e) => e.key === 'Enter' && submit()} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="password">密码</Label>
            <Input id="password" type="password" value={password} autoComplete="current-password"
                   onChange={(e) => { setPassword(e.target.value); setErr('') }}
                   onKeyDown={(e) => e.key === 'Enter' && submit()} />
          </div>
          {err && (
            <Alert variant="destructive">
              <AlertDescription>{err}</AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter>
          <Button className="w-full" disabled={!name.trim() || !password || busy} onClick={submit}>
            {busy ? '登录中…' : '登录'}
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
