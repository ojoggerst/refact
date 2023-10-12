import os
import subprocess

from typing import Union
from pathlib import Path

from fastapi import APIRouter, UploadFile
from fastapi.responses import JSONResponse

from self_hosting_machinery import env
from self_hosting_machinery.webgui.selfhost_webutils import log
from self_hosting_machinery.webgui.tab_upload import download_file_from_url, UploadViaURL


def rm(f):
    try:
        subprocess.check_call(["rm", "-rf", f])
    except Exception as e:
        log(f"Error while removing file: {e}")


async def unpack(file_path: Path) -> JSONResponse:
    def get_mimetype(fp: Union[str, Path]) -> str:
        m = subprocess.check_output(["file", "--mime-type", "-b", fp])
        return m.decode("utf-8").strip()

    upload_filename = str(file_path)
    unpack_filename = str(file_path.parent)

    if not file_path.is_file():
        return JSONResponse({"detail": f"Error while unpacking: File {file_path.name} does not exist"}, status_code=404)

    try:
        mime_type = get_mimetype(upload_filename)
        if 'application/x-tar' in mime_type:
            cmd = ["tar", "-xf", upload_filename, "-C", unpack_filename]
        elif 'application/x-bzip2' in mime_type:
            cmd = ["tar", "-xjf", upload_filename, "-C", unpack_filename]
        elif 'application/x-gzip' in mime_type:
            cmd = ["tar", "-xzf", upload_filename, "-C", unpack_filename]
        elif 'application/zip' in mime_type:
            cmd = ["unzip", "-q", "-o", upload_filename, "-d", unpack_filename]
        else:
            return JSONResponse({"detail": f"Error while unpacking: Unknown archive type {mime_type}"}, status_code=400)
        subprocess.check_call(cmd)
        rm(os.path.join(unpack_filename, file_path.name))
        return JSONResponse("OK", status_code=200)

    except Exception as e:
        log(f"Error while unpacking: {e}")
        return JSONResponse({"detail": f"Error while unpacking: {e}"}, status_code=500)


class TabLorasRouter(APIRouter):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_api_route("/lora-upload", self._upload_lora, methods=["POST"])
        self.add_api_route("/lora-upload-url", self._upload_lora_url, methods=["POST"])

    async def _upload_lora(self, file: UploadFile):
        async def write_to_file() -> JSONResponse:
            upload_dest = env.DIR_LORAS
            tmp_path = os.path.join(upload_dest, file.filename + ".tmp")
            file_path = os.path.join(upload_dest, file.filename)
            if os.path.exists(file_path):
                return JSONResponse({"detail": f"File with this name already exists"}, status_code=409)
            try:
                with open(tmp_path, "wb") as f:
                    while True:
                        if not (contents := await file.read(1024 * 1024)):
                            break
                        f.write(contents)
                os.rename(tmp_path, file_path)
                return JSONResponse("OK", status_code=200)
            except OSError as e:
                log("Error while uploading file: %s" % (e or str(type(e))))
                return JSONResponse({"detail": "Cannot upload file, see logs for details"}, status_code=500)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        f = Path(os.path.join(env.DIR_LORAS, file.filename))

        if (resp := await write_to_file()).status_code != 200:
            rm(f)
            return resp

        if (resp := await unpack(f)).status_code != 200:
            rm(f)
            return resp

        return JSONResponse("OK", status_code=200)

    async def _upload_lora_url(self, file: UploadViaURL):
        try:
            file_path = await download_file_from_url(file.url, env.DIR_LORAS)
        except Exception as e:
            return JSONResponse({"detail": f"Cannot download: {e}"}, status_code=500)

        resp = await unpack(Path(file_path))
        rm(file_path)
        if resp.status_code != 200:
            return resp
        return JSONResponse("OK", status_code=200)
