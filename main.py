from fastapi import FastAPI, HTTPException
import subprocess
import asyncio
import json
import re

app = FastAPI(title="컴시간 시간표 API")

def run_node_script(node_script: str):
    """
    Render(Linux) 및 Windows 환경 모두에서 Node.js 스크립트를 안정적으로 실행.
    stdout과 stderr를 함께 수집하여 에러 발생 원인을 명확하게 전달합니다.
    """
    result = subprocess.run(
        ["node", "-e", node_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        shell=False
    )
    stdout_res = result.stdout.strip() if result.stdout else ""
    stderr_res = result.stderr.strip() if result.stderr else ""
    return stdout_res, stderr_res

@app.get("/")
def read_root():
    return {"status": "ok", "message": "시간표 API 서버가 정상 작동 중입니다."}

@app.get("/timetable/{school_name}")
async def get_timetable(
    school_name: str, 
    grade: int = None, 
    class_num: int = None, 
    region: str = None
):
    node_script = f"""
    const Timetable = require('comcigan-parser');
    const timetable = new Timetable();

    async function run() {{
        await timetable.init({{ cache: 1000 * 60 * 30 }});
        
        const schoolList = await timetable.search('{school_name}');
        if (!schoolList || schoolList.length === 0) {{
            console.log("---JSON_START---");
            console.log(JSON.stringify({{ error: "해당 학교를 찾을 수 없습니다." }}));
            console.log("---JSON_END---");
            return;
        }}

        let targetSchool = schoolList[0];
        const reqRegion = '{region or ""}';
        if (reqRegion) {{
            const found = schoolList.find(s => 
                (s.region && s.region.includes(reqRegion)) || 
                (s.name && s.name.includes(reqRegion))
            );
            if (found) targetSchool = found;
        }}

        await timetable.setSchool(targetSchool.code);
        
        const result = await timetable.getTimetable();
        const classTime = await timetable.getClassTime();

        console.log("---JSON_START---");
        console.log(JSON.stringify({{
            school: targetSchool.name,
            region: targetSchool.region,
            code: targetSchool.code,
            timetable: result,
            classTime: classTime
        }}));
        console.log("---JSON_END---");
    }}

    run().catch(err => {{
        const errMsg = (err && (err.stack || err.message || err.toString())) || "알 수 없는 Node.js 오류";
        console.log("---JSON_START---");
        console.log(JSON.stringify({{ error: errMsg }}));
        console.log("---JSON_END---");
    }});
    """

    try:
        # 이벤트 루프에서 동기 subprocess 실행
        loop = asyncio.get_event_loop()
        stdout, stderr = await loop.run_in_executor(None, run_node_script, node_script)

        # Node.js 내부 에러 또는 모듈 로딩 실패 처리
        if stderr and "Error" in stderr and not stdout:
            raise HTTPException(status_code=500, detail=f"Node 실행 에러: {stderr}")

        if not stdout:
            detail_msg = f"Node.js 응답이 비어있습니다. (stderr: {stderr})" if stderr else "Node.js 응답 데이터가 비어 있습니다."
            raise HTTPException(status_code=500, detail=detail_msg)

        match = re.search(r'---JSON_START---\s*(\{.*?\})\s*---JSON_END---', stdout, re.DOTALL)
        if not match:
            raise HTTPException(status_code=500, detail=f"Node.js 출력 파싱 실패: {stdout}")

        json_str = match.group(1)
        output = json.loads(json_str)
        
        if "error" in output:
            raise HTTPException(status_code=400, detail=output["error"])

        timetable_data = output["timetable"]

        # 특정 학년/반 필터링
        if grade is not None and class_num is not None:
            grade_data = timetable_data.get(grade) or timetable_data.get(str(grade))
            if not grade_data:
                raise HTTPException(status_code=400, detail=f"{grade}학년 정보를 찾을 수 없습니다.")
                
            class_timetable = grade_data.get(class_num) or grade_data.get(str(class_num))
            if class_timetable is None:
                raise HTTPException(status_code=400, detail=f"{grade}학년 {class_num}반 정보를 찾을 수 없습니다.")

            return {
                "school": output["school"],
                "region": output["region"],
                "grade": grade,
                "class": class_num,
                "timetable": class_timetable,
                "classTime": output["classTime"]
            }

        return {
            "school": output["school"],
            "region": output["region"],
            "timetable": timetable_data,
            "classTime": output["classTime"]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 내부 처리 에러: {type(e).__name__} - {str(e)}")