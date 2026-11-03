"""GeneScope 2 uses the existing process supervisor with a v2 integrity manifest."""
from pathlib import Path
from cloud_deployment import serve
from cloud_deployment.platform2_release import verify

def main():
    serve.verify_content=lambda root: verify(Path(root),code_only=True)
    serve.main()

if __name__=='__main__':
    main()
