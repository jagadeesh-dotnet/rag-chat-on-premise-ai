import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ChatRoutingModule } from './chat-routing.module';
import { ChatComponent } from './chat/chat.component';
import { MarkdownPipe } from './markdown.pipe';
import { ResultCardComponent } from './result-card/result-card.component';
import { ResultChartComponent } from './result-chart/result-chart.component';
import { SidebarComponent } from './sidebar/sidebar.component';

@NgModule({
  declarations: [ChatComponent, SidebarComponent, ResultCardComponent, ResultChartComponent, MarkdownPipe],
  imports: [CommonModule, FormsModule, ChatRoutingModule],
})
export class ChatModule {}
