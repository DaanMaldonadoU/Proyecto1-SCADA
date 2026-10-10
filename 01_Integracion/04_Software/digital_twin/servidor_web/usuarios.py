# -*- coding: utf-8 -*-
"""
digital_twin/servidor_web/usuarios.py — Cuentas, sesiones y auditoría del servidor del gemelo (SQLite).

Qué guarda (archivo digital_twin/datos/gemelo.sqlite, ignorado por git):
    usuarios   (usuario, hash, sal, rol, activo, creado, ultimo_acceso)
               Contraseñas con PBKDF2-HMAC-SHA256 (240 000 iteraciones, sal de 16 bytes).
    sesiones   (token_hash, usuario, creada, expira, ip). Del token solo se guarda su SHA-256:
               quien lea la base no puede suplantar sesiones.
    auditoria  (t, usuario, rol, ip, accion, detalle, ok, msg). Cada orden, inicio de sesión y
               cambio de cuentas, con hora. Es el registro de "quién hizo qué y cuándo".

Roles: los de core.mando.ROLES (usuario, operador, ingeniero, admin).
Compatibilidad: Python 3.12 a 3.13, solo biblioteca estándar.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time

from core.mando import ROLES

ITERACIONES = 240000
DURACION_SESION_S = 12 * 3600
PATRON_USUARIO = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
MIN_CLAVE = 8


def hash_clave(clave, sal_hex):
    """PBKDF2 de la contraseña. Es lento a propósito (~0,1 s): llamar fuera del bucle asyncio."""
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(sal_hex), ITERACIONES).hex()


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Almacen:
    def __init__(self, ruta):
        carpeta = os.path.dirname(os.path.abspath(ruta))
        os.makedirs(carpeta, exist_ok=True)
        self.db = sqlite3.connect(ruta)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS usuarios (
                usuario TEXT PRIMARY KEY, hash TEXT NOT NULL, sal TEXT NOT NULL, rol TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1, creado REAL, ultimo_acceso REAL);
            CREATE TABLE IF NOT EXISTS sesiones (
                token_hash TEXT PRIMARY KEY, usuario TEXT NOT NULL, creada REAL, expira REAL, ip TEXT);
            CREATE TABLE IF NOT EXISTS auditoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, usuario TEXT, rol TEXT, ip TEXT,
                accion TEXT, detalle TEXT, ok INTEGER, msg TEXT);
            CREATE INDEX IF NOT EXISTS auditoria_t ON auditoria(t);
        """)
        self.db.commit()

    def cerrar(self):
        self.db.close()

    # ------------------------------------------------------------------ cuentas
    @staticmethod
    def validar_datos(usuario, clave=None, rol=None):
        if usuario is not None and not PATRON_USUARIO.match(usuario or ""):
            return "usuario inválido (3-32 caracteres: letras, números, . _ -)"
        if clave is not None and len(clave) < MIN_CLAVE:
            return "la contraseña debe tener al menos %d caracteres" % MIN_CLAVE
        if rol is not None and rol not in ROLES:
            return "rol inválido; opciones: %s" % ", ".join(ROLES)
        return None

    def crear_usuario(self, usuario, clave, rol):
        err = self.validar_datos(usuario, clave, rol)
        if err:
            raise ValueError(err)
        if self.usuario(usuario):
            raise ValueError("ya existe el usuario %s" % usuario)
        sal = secrets.token_hex(16)
        self.db.execute("INSERT INTO usuarios (usuario, hash, sal, rol, activo, creado) VALUES (?,?,?,?,1,?)",
                        (usuario, hash_clave(clave, sal), sal, rol, time.time()))
        self.db.commit()

    def cambiar_clave(self, usuario, clave):
        err = self.validar_datos(None, clave)
        if err:
            raise ValueError(err)
        sal = secrets.token_hex(16)
        n = self.db.execute("UPDATE usuarios SET hash=?, sal=? WHERE usuario=?",
                            (hash_clave(clave, sal), sal, usuario)).rowcount
        self.db.execute("DELETE FROM sesiones WHERE usuario=?", (usuario,))
        self.db.commit()
        return n > 0

    def cambiar_rol(self, usuario, rol):
        err = self.validar_datos(None, None, rol)
        if err:
            raise ValueError(err)
        n = self.db.execute("UPDATE usuarios SET rol=? WHERE usuario=?", (rol, usuario)).rowcount
        self.db.commit()
        return n > 0

    def activar(self, usuario, activo):
        n = self.db.execute("UPDATE usuarios SET activo=? WHERE usuario=?", (1 if activo else 0, usuario)).rowcount
        if not activo:
            self.db.execute("DELETE FROM sesiones WHERE usuario=?", (usuario,))
        self.db.commit()
        return n > 0

    def borrar(self, usuario):
        n = self.db.execute("DELETE FROM usuarios WHERE usuario=?", (usuario,)).rowcount
        self.db.execute("DELETE FROM sesiones WHERE usuario=?", (usuario,))
        self.db.commit()
        return n > 0

    def usuario(self, usuario):
        fila = self.db.execute("SELECT * FROM usuarios WHERE usuario=?", (usuario,)).fetchone()
        return dict(fila) if fila else None

    def listar(self):
        return [{"usuario": f["usuario"], "rol": f["rol"], "activo": bool(f["activo"]),
                 "creado": f["creado"], "ultimo_acceso": f["ultimo_acceso"]}
                for f in self.db.execute("SELECT * FROM usuarios ORDER BY usuario")]

    def hay_admin(self):
        return self.db.execute("SELECT 1 FROM usuarios WHERE rol='admin' AND activo=1").fetchone() is not None

    def comprobar(self, usuario, clave):
        """Devuelve la cuenta si la contraseña es correcta y está activa; None si no.
        Lento (PBKDF2): llamar con run_in_executor desde asyncio."""
        u = self.usuario(usuario) if usuario else None
        if u is None:
            hash_clave(clave or "", "00" * 16)          # mismo tiempo exista o no el usuario
            return None
        if not hmac.compare_digest(hash_clave(clave or "", u["sal"]), u["hash"]) or not u["activo"]:
            return None
        return {"usuario": u["usuario"], "rol": u["rol"]}

    # ------------------------------------------------------------------ sesiones
    def crear_sesion(self, usuario, ip):
        token = secrets.token_urlsafe(32)
        ahora = time.time()
        self.db.execute("INSERT INTO sesiones VALUES (?,?,?,?,?)",
                        (_hash_token(token), usuario, ahora, ahora + DURACION_SESION_S, ip))
        self.db.execute("UPDATE usuarios SET ultimo_acceso=? WHERE usuario=?", (ahora, usuario))
        self.db.execute("DELETE FROM sesiones WHERE expira < ?", (ahora,))
        self.db.commit()
        return token

    def sesion(self, token):
        """Cuenta {"usuario", "rol"} de un token vigente, o None."""
        if not token:
            return None
        fila = self.db.execute(
            "SELECT u.usuario, u.rol, u.activo, s.expira FROM sesiones s JOIN usuarios u ON u.usuario = s.usuario "
            "WHERE s.token_hash=?", (_hash_token(token),)).fetchone()
        if not fila or not fila["activo"] or fila["expira"] < time.time():
            return None
        return {"usuario": fila["usuario"], "rol": fila["rol"]}

    def cerrar_sesion(self, token):
        self.db.execute("DELETE FROM sesiones WHERE token_hash=?", (_hash_token(token or ""),))
        self.db.commit()

    # ------------------------------------------------------------------ auditoría
    def auditar(self, usuario, rol, ip, accion, detalle, ok, msg, t=None):
        t = time.time() if t is None else t
        self.db.execute("INSERT INTO auditoria (t, usuario, rol, ip, accion, detalle, ok, msg) VALUES (?,?,?,?,?,?,?,?)",
                        (t, usuario, rol, ip, accion, detalle, 1 if ok else 0, msg))
        self.db.commit()
        return {"t": t, "usuario": usuario, "rol": rol, "accion": accion, "detalle": detalle,
                "ok": bool(ok), "msg": msg}

    def auditoria(self, n=200):
        filas = self.db.execute("SELECT t, usuario, rol, ip, accion, detalle, ok, msg FROM auditoria "
                                "ORDER BY id DESC LIMIT ?", (int(n),))
        return [dict(f) for f in filas]
