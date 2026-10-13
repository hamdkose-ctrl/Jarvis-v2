import com.sun.source.util.JavacTask;
import javax.tools.*;
import java.util.*;

/** Parse all Android source syntax; deliberately does not resolve SDK symbols. */
public class ParseSources {
    public static void main(String[] paths) throws Exception {
        JavaCompiler compiler=ToolProvider.getSystemJavaCompiler();
        DiagnosticCollector<JavaFileObject> diagnostics=new DiagnosticCollector<>();
        try(StandardJavaFileManager files=compiler.getStandardFileManager(diagnostics,null,null)) {
            JavacTask task=(JavacTask)compiler.getTask(null,files,diagnostics,List.of("-proc:none"),null,files.getJavaFileObjects(paths));
            for(Object tree:task.parse()) {}
            for(Diagnostic<?> diagnostic:diagnostics.getDiagnostics())
                if(diagnostic.getKind()==Diagnostic.Kind.ERROR)throw new AssertionError(diagnostic.toString());
        }
        System.out.println("All Android source syntax parsed; SDK semantics not checked");
    }
}
