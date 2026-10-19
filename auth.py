"""Login con cuenta Microsoft (Minecraft Premium) usando Device Code nativo con requests.
No requiere registrar apps en Azure ni levantar servidores locales.
Guarda la sesión en disco de forma permanente.
"""
import json
import os
import time
import webbrowser
import requests

CLIENT_ID_PUBLICO = "000000004c12ae6f"


class AuthError(Exception):
    pass


class MicrosoftAuth:
    def __init__(self, ruta_guardado, client_id=CLIENT_ID_PUBLICO):
        self.client_id = client_id
        self.ruta = ruta_guardado

    def _guardar(self, data):
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def tiene_sesion_guardada(self):
        return os.path.isfile(self.ruta)

    def cerrar_sesion(self):
        if os.path.isfile(self.ruta):
            os.remove(self.ruta)

    def obtener_sesion_guardada(self):
        """Lee los datos guardados en el disco sin contactar a Microsoft."""
        if not self.tiene_sesion_guardada():
            return None
        try:
            with open(self.ruta, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("name") and data.get("access_token"):
                    return data
        except Exception:
            return None
        return None

    def _intercambiar_tokens(self, ms_access_token, refresh_token=None):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # 1. Xbox Live (con soporte para ticket directo y fallback)
        ticket = ms_access_token if (ms_access_token.startswith("d=") or ms_access_token.startswith("t=")) else f"d={ms_access_token}"
        xbl_payload = {
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": ticket
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT"
        }

        res_xbl = requests.post(
            "https://user.auth.xboxlive.com/user/authenticate",
            json=xbl_payload,
            headers=headers,
            timeout=15
        )

        if res_xbl.status_code != 200:
            token_clean = ms_access_token.replace("d=", "").replace("t=", "")
            xbl_payload["Properties"]["RpsTicket"] = f"t={token_clean}"
            res_xbl = requests.post(
                "https://user.auth.xboxlive.com/user/authenticate",
                json=xbl_payload,
                headers=headers,
                timeout=15
            )

        if res_xbl.status_code != 200:
            print(f"[DEBUG XboxLive] Status: {res_xbl.status_code} | Respuesta: {res_xbl.text}")
            raise AuthError("Error al autenticar con Xbox Live")

        xbl_data = res_xbl.json()
        xbl_token = xbl_data["Token"]
        userhash = xbl_data["DisplayClaims"]["xui"][0]["uhs"]

        # 2. Token XSTS para Minecraft
        res_xsts = requests.post(
            "https://xsts.auth.xboxlive.com/xsts/authorize",
            json={
                "Properties": {
                    "SandboxId": "RETAIL",
                    "UserTokens": [xbl_token]
                },
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType": "JWT"
            },
            headers=headers,
            timeout=15
        )

        if res_xsts.status_code != 200:
            print(f"[DEBUG XSTS] Status: {res_xsts.status_code} | Respuesta: {res_xsts.text}")
            err_data = res_xsts.json()
            if err_data.get("XErr") == 2148916238:
                raise AuthError("Cuenta de menor sin familia Microsoft configurada")
            raise AuthError("Error al obtener token XSTS")

        xsts_token = res_xsts.json()["Token"]

        # 3. Autenticación en Minecraft Services
        res_mc = requests.post(
            "https://api.minecraftservices.com/authentication/login_with_xbox",
            json={"identityToken": f"XBL3.0 x={userhash};{xsts_token}"},
            headers=headers,
            timeout=15
        )

        if res_mc.status_code != 200:
            print(f"[DEBUG Minecraft Auth] Status: {res_mc.status_code} | Respuesta: {res_mc.text}")
            raise AuthError("Error al obtener token de Minecraft")

        mc_token = res_mc.json()["access_token"]

        # 4. Obtener perfil de Minecraft Java
        res_profile = requests.get(
            "https://api.minecraftservices.com/minecraft/profile",
            headers={"Authorization": f"Bearer {mc_token}"},
            timeout=15
        )

        if res_profile.status_code == 404:
            raise AuthError("Esa cuenta no tiene Minecraft Java comprado")
        if res_profile.status_code != 200:
            print(f"[DEBUG Profile] Status: {res_profile.status_code} | Respuesta: {res_profile.text}")
            raise AuthError("Error al obtener perfil de Minecraft")

        profile = res_profile.json()

        datos_sesion = {
            "name": profile["name"],
            "id": profile["id"],
            "access_token": mc_token,
            "refresh_token": refresh_token
        }
        self._guardar(datos_sesion)
        return datos_sesion

    def refrescar(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos_locales = json.load(f)
                rt = datos_locales.get("refresh_token")
        except Exception:
            raise AuthError("No hay sesión guardada")

        if not rt:
            if datos_locales.get("access_token"):
                return datos_locales
            raise AuthError("No hay token disponible")

        try:
            res = requests.post(
                "https://login.live.com/oauth20_token.srf",
                data={
                    "client_id": self.client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": rt,
                    "scope": "service::user.auth.xboxlive.com::MBI_SSL"
                },
                timeout=15
            )

            if res.status_code == 200:
                token_data = res.json()
                return self._intercambiar_tokens(
                    token_data["access_token"],
                    token_data.get("refresh_token", rt)
                )
            else:
                if datos_locales.get("access_token"):
                    return datos_locales
                self.cerrar_sesion()
                raise AuthError("La sesión ha expirado")
        except Exception as e:
            if datos_locales.get("access_token"):
                return datos_locales
            raise AuthError(f"Error al refrescar sesión: {e}")

    def login_interactivo(self, callback_codigo=None):
        res = requests.post(
            "https://login.live.com/oauth20_connect.srf",
            data={
                "client_id": self.client_id,
                "scope": "service::user.auth.xboxlive.com::MBI_SSL",
                "response_type": "device_code"
            },
            timeout=15
        )

        if res.status_code != 200:
            print(f"[DEBUG DeviceCode] {res.status_code} - {res.text}")
            raise AuthError(f"HTTP {res.status_code}: Error al pedir código")

        dc_data = res.json()
        device_code = dc_data["device_code"]
        user_code = dc_data["user_code"]
        verification_uri = dc_data.get("verification_uri", "https://microsoft.com/link")
        interval = dc_data.get("interval", 5)

        webbrowser.open(verification_uri)

        if callback_codigo:
            callback_codigo(verification_uri, user_code)

        token_endpoint = "https://login.live.com/oauth20_token.srf"
        poll_data = {
            "client_id": self.client_id,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code
        }

        while True:
            time.sleep(interval)
            r = requests.post(token_endpoint, data=poll_data, timeout=15)
            r_json = r.json()

            if r.status_code == 200:
                return self._intercambiar_tokens(
                    r_json["access_token"],
                    r_json.get("refresh_token")
                )

            error = r_json.get("error")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval += 5
                continue
            elif error in ("expired_token", "code_expired"):
                raise AuthError("El código expiró. Intenta de nuevo.")
            else:
                desc = r_json.get("error_description", error)
                print(f"[DEBUG Token Poll] Error: {desc}")
                raise AuthError(f"Error: {desc}")