// 登录页（演示壳）：校验演示账号表后放行；服务端权限仍走 X-Adkg-Role → token（§9.7）
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ACCOUNTS } from '@/lib/accounts'
import { useSession } from '@/lib/session'

export function LoginPage() {
  const { login } = useSession()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')

  const submit = () => {
    const account = ACCOUNTS.find((a) => a.name === name.trim())
    if (!account || account.password !== password) {
      setErr('账号或密码不对（演示账号找管理员要）')
      return
    }
    login({
      account: account.name, label: account.label,
      admin: account.admin ?? false, persona: account.persona,
    })
    navigate('/', { replace: true })
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl font-extrabold tracking-wide">AdKG</CardTitle>
          <CardDescription>本体驱动的广告营销知识中台 · 演示登录</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="account">账号</Label>
            <Input id="account" value={name} autoComplete="username"
                   placeholder="如：chen / gu / admin"
                   onChange={(e) => { setName(e.target.value); setErr('') }}
                   onKeyDown={(e) => e.key === 'Enter' && name && password && submit()} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="password">密码</Label>
            <Input id="password" type="password" value={password} autoComplete="current-password"
                   onChange={(e) => { setPassword(e.target.value); setErr('') }}
                   onKeyDown={(e) => e.key === 'Enter' && name && password && submit()} />
          </div>
          {err && (
            <Alert variant="destructive">
              <AlertDescription>{err}</AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter>
          <Button className="w-full" disabled={!name.trim() || !password} onClick={submit}>
            登录
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
